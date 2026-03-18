from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
import json
import logging
import os

import polars as pl
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException, Query
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware


ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = ROOT_DIR.parent / "data"
ITEMS_FILE = DATA_DIR / "items.parquet"
TRANSACTIONS_FILE = DATA_DIR / "transactions-2025-12.parquet"
RECOMMENDATIONS_FILE = DATA_DIR / "recommendations_all.json"

TA_QUERY_VARIANTS = {"tã", "Tã", "tÃ", "TÃ"}

app = FastAPI()
api_router = APIRouter(prefix="/api")


# ==============================
# Schemas
# ==============================
class ProductItem(BaseModel):
    item_id: str
    name: str
    brand: str
    category_l1: str
    price: float
    sale_status: int
    rating: Optional[float] = None


class ProductCatalogResponse(BaseModel):
    total: int
    items: List[ProductItem]


class ProductFiltersResponse(BaseModel):
    categories: List[str]
    brands: List[str]


class RecommendedItem(ProductItem):
    frequency: Optional[int] = None
    relevance_score: Optional[int] = None


class RecommendationResponse(BaseModel):
    target_item_id: str
    frequently_bought_together: List[RecommendedItem]
    relevant: List[RecommendedItem]


class SearchSuggestedItem(BaseModel):
    item_id: str
    name: str
    price: float
    sale_status: int


class UpsellSuggestion(SearchSuggestedItem):
    size: Optional[str] = None
    score: float


class SearchRecommendationResponse(BaseModel):
    query: str
    matched_item_id: Optional[str] = None
    similar_items: List[SearchSuggestedItem]
    upsell_recommendations: List[UpsellSuggestion]
    is_ta_query: bool


class ItemRuleRecommendationResponse(BaseModel):
    target_item_id: str
    item_type: Optional[str] = None
    has_rule: bool
    similar_items: List[SearchSuggestedItem]
    upsell_recommendations: List[UpsellSuggestion]


_cache: Dict[str, object] = {
    "items_df": None,
    "items_mtime": None,
    "transactions_df": None,
    "transactions_mtime": None,
    "recommendations_rules": None,
    "recommendations_mtime": None,
}


# ==============================
# Helpers
# ==============================
def _first_existing(columns: List[str], candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in columns:
            return c
    return None


def _safe_score(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_ta_query(query_text: str) -> bool:
    return any(v in query_text for v in TA_QUERY_VARIANTS)


def _is_ta_type(item_type: object) -> bool:
    return str(item_type or "").strip() in TA_QUERY_VARIANTS


def _normalized_items_df() -> pl.DataFrame:
    if not ITEMS_FILE.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Missing data file: {ITEMS_FILE}. Please add items.parquet to /data.",
        )

    raw_df = pl.read_parquet(ITEMS_FILE)
    cols = raw_df.columns

    item_id_col = _first_existing(cols, ["item_id", "itemId", "sku", "product_id", "id"])
    name_col = _first_existing(cols, ["name", "item_name", "product_name", "title", "category"])
    brand_col = _first_existing(cols, ["brand", "brand_name", "manufacturer"])
    category_col = _first_existing(cols, ["category_l1", "category", "category_name", "department"])
    price_col = _first_existing(cols, ["price", "price_vnd", "sale_price", "selling_price"])
    sale_status_col = _first_existing(cols, ["sale_status", "status", "is_active", "available"])
    rating_col = _first_existing(cols, ["rating", "avg_rating", "stars"])

    required = {
        "item_id": item_id_col,
        "name": name_col,
        "price": price_col,
    }
    missing = [k for k, v in required.items() if v is None]
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"items.parquet is missing required fields: {', '.join(missing)}",
        )

    selection = [
        pl.col(item_id_col).cast(pl.Utf8).alias("item_id"),
        pl.col(name_col).cast(pl.Utf8).alias("name"),
        (pl.col(brand_col).cast(pl.Utf8).alias("brand") if brand_col else pl.lit("Unknown brand").alias("brand")),
        (
            pl.col(category_col).cast(pl.Utf8).alias("category_l1")
            if category_col
            else pl.lit("Uncategorized").alias("category_l1")
        ),
        pl.col(price_col).cast(pl.Float64, strict=False).alias("price"),
        (
            pl.col(sale_status_col).cast(pl.Int64, strict=False).alias("sale_status")
            if sale_status_col
            else pl.lit(1).alias("sale_status")
        ),
        (
            pl.col(rating_col).cast(pl.Float64, strict=False).alias("rating")
            if rating_col
            else pl.lit(None).cast(pl.Float64).alias("rating")
        ),
    ]

    return (
        raw_df.select(selection)
        .with_columns(
            [
                pl.col("item_id").fill_null(""),
                pl.col("name").fill_null("Unknown item"),
                pl.col("brand").fill_null("Unknown brand"),
                pl.col("category_l1").fill_null("Uncategorized"),
                pl.col("price").fill_null(0.0),
                pl.col("sale_status").fill_null(0),
            ]
        )
        .filter(pl.col("item_id") != "")
        .unique(subset=["item_id"], keep="first")
    )


def _normalized_transactions_df() -> pl.DataFrame:
    if not TRANSACTIONS_FILE.exists():
        return pl.DataFrame({"customer_id": [], "item_id": []})

    raw_df = pl.read_parquet(TRANSACTIONS_FILE)
    cols = raw_df.columns

    customer_col = _first_existing(cols, ["customer_id", "user_id", "buyer_id"])
    item_id_col = _first_existing(cols, ["item_id", "itemId", "product_id", "sku"])

    if customer_col is None or item_id_col is None:
        return pl.DataFrame({"customer_id": [], "item_id": []})

    return (
        raw_df.select(
            [
                pl.col(customer_col).cast(pl.Utf8).alias("customer_id"),
                pl.col(item_id_col).cast(pl.Utf8).alias("item_id"),
            ]
        )
        .with_columns([pl.col("customer_id").fill_null(""), pl.col("item_id").fill_null("")])
        .filter((pl.col("customer_id") != "") & (pl.col("item_id") != ""))
    )


def _get_items_df() -> pl.DataFrame:
    mtime = ITEMS_FILE.stat().st_mtime if ITEMS_FILE.exists() else None
    if _cache["items_df"] is None or _cache["items_mtime"] != mtime:
        _cache["items_df"] = _normalized_items_df()
        _cache["items_mtime"] = mtime
    return _cache["items_df"]


def _get_transactions_df() -> pl.DataFrame:
    mtime = TRANSACTIONS_FILE.stat().st_mtime if TRANSACTIONS_FILE.exists() else None
    if _cache["transactions_df"] is None or _cache["transactions_mtime"] != mtime:
        _cache["transactions_df"] = _normalized_transactions_df()
        _cache["transactions_mtime"] = mtime
    return _cache["transactions_df"]


def _get_recommendation_rules() -> Dict[str, Dict[str, Any]]:
    mtime = RECOMMENDATIONS_FILE.stat().st_mtime if RECOMMENDATIONS_FILE.exists() else None
    if _cache["recommendations_rules"] is not None and _cache["recommendations_mtime"] == mtime:
        return _cache["recommendations_rules"]  # type: ignore[return-value]

    if not RECOMMENDATIONS_FILE.exists():
        _cache["recommendations_rules"] = {}
        _cache["recommendations_mtime"] = None
        return {}

    parsed_entries: List[Dict[str, Any]] = []
    try:
        with RECOMMENDATIONS_FILE.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        if isinstance(payload, list):
            parsed_entries = [x for x in payload if isinstance(x, dict)]
        elif isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                parsed_entries = [x for x in payload["data"] if isinstance(x, dict)]
            elif "item_id" in payload:
                parsed_entries = [payload]
            else:
                for key, value in payload.items():
                    if isinstance(value, dict):
                        v = {**value}
                        v.setdefault("item_id", str(key))
                        parsed_entries.append(v)
    except Exception:
        parsed_entries = []

    indexed: Dict[str, Dict[str, Any]] = {}
    for entry in parsed_entries:
        iid = str(entry.get("item_id", "")).strip()
        if iid:
            indexed[iid] = entry

    _cache["recommendations_rules"] = indexed
    _cache["recommendations_mtime"] = mtime
    return indexed


def _row_to_item(row: Dict[str, object]) -> ProductItem:
    return ProductItem(
        item_id=str(row.get("item_id", "")),
        name=str(row.get("name", "Unknown item")),
        brand=str(row.get("brand", "Unknown brand")),
        category_l1=str(row.get("category_l1", "Uncategorized")),
        price=float(row.get("price", 0.0) or 0.0),
        sale_status=int(row.get("sale_status", 0) or 0),
        rating=(float(row["rating"]) if row.get("rating") is not None else None),
    )


def _row_to_search_item(row: Dict[str, object]) -> SearchSuggestedItem:
    return SearchSuggestedItem(
        item_id=str(row.get("item_id", "")),
        name=str(row.get("name", "Unknown item")),
        price=float(row.get("price", 0.0) or 0.0),
        sale_status=int(row.get("sale_status", 0) or 0),
    )


def _search_items_df(items_df: pl.DataFrame, query_text: str) -> pl.DataFrame:
    term = query_text.strip().lower()
    if not term:
        return items_df.head(0)

    return items_df.filter(
        pl.col("name").str.to_lowercase().str.contains(term, literal=True)
        | pl.col("brand").str.to_lowercase().str.contains(term, literal=True)
        | pl.col("item_id").str.to_lowercase().str.contains(term, literal=True)
        | pl.col("category_l1").str.to_lowercase().str.contains(term, literal=True)
    )


# ==============================
# Routes
# ==============================
@api_router.get("/")
async def root():
    return {"message": "Recommendation API is live"}


@api_router.get("/items/meta", response_model=ProductFiltersResponse)
async def list_filter_metadata():
    items_df = _get_items_df().filter(pl.col("sale_status") == 1)

    categories = (
        items_df.select("category_l1")
        .drop_nulls()
        .unique()
        .sort("category_l1")
        .to_series()
        .to_list()
    )
    brands = (
        items_df.select("brand")
        .drop_nulls()
        .unique()
        .sort("brand")
        .to_series()
        .to_list()
    )
    return ProductFiltersResponse(
        categories=[str(v) for v in categories if str(v).strip()],
        brands=[str(v) for v in brands if str(v).strip()],
    )


@api_router.get("/items", response_model=ProductCatalogResponse)
async def list_items(
    q: str = Query(default="", max_length=120),
    category: str = Query(default="", max_length=120),
    brand: str = Query(default="", max_length=120),
    sort_by: Literal["name", "price", "brand", "item_id"] = "name",
    sort_dir: Literal["asc", "desc"] = "asc",
    limit: int = Query(default=24, ge=1, le=120),
    offset: int = Query(default=0, ge=0),
):
    df = _get_items_df().filter(pl.col("sale_status") == 1)

    if q.strip():
        df = _search_items_df(df, q)

    if category.strip():
        c = category.strip().lower()
        df = df.filter(pl.col("category_l1").str.to_lowercase() == c)

    if brand.strip():
        b = brand.strip().lower()
        df = df.filter(pl.col("brand").str.to_lowercase() == b)

    total = df.height
    paged_df = df.sort(sort_by, descending=(sort_dir == "desc")).slice(offset, limit)

    return ProductCatalogResponse(total=total, items=[_row_to_item(r) for r in paged_df.to_dicts()])


@api_router.get("/search-recommendations", response_model=SearchRecommendationResponse)
async def get_search_recommendations(q: str = Query(default="", max_length=120)):
    query_text = q.strip()
    is_ta = _is_ta_query(query_text)

    if not query_text:
        return SearchRecommendationResponse(
            query="",
            matched_item_id=None,
            similar_items=[],
            upsell_recommendations=[],
            is_ta_query=is_ta,
        )

    items_df = _get_items_df()
    matches = _search_items_df(items_df, query_text)
    if matches.height == 0:
        return SearchRecommendationResponse(
            query=query_text,
            matched_item_id=None,
            similar_items=[],
            upsell_recommendations=[],
            is_ta_query=is_ta,
        )

    matched_item = matches.sort("name").to_dicts()[0]
    matched_item_id = str(matched_item.get("item_id", ""))
    item_map = {
        str(r.get("item_id", "")).strip(): r
        for r in items_df.to_dicts()
        if str(r.get("item_id", "")).strip()
    }

    rule = _get_recommendation_rules().get(matched_item_id, {})

    similar_items: List[SearchSuggestedItem] = []
    for sid in rule.get("similar_items", []):
        row = item_map.get(str(sid).strip())
        if row:
            similar_items.append(_row_to_search_item(row))

    upsell_items: List[UpsellSuggestion] = []
    if is_ta:
        temp: List[UpsellSuggestion] = []
        for u in rule.get("upsell_recommendations", []):
            if not isinstance(u, dict):
                continue
            uid = str(u.get("item_id", "")).strip()
            if not uid or uid not in item_map:
                continue
            temp.append(
                UpsellSuggestion(
                    **_row_to_search_item(item_map[uid]).model_dump(),
                    size=(str(u.get("size")) if u.get("size") is not None else None),
                    score=_safe_score(u.get("score")),
                )
            )
        temp.sort(key=lambda x: x.score, reverse=True)
        upsell_items = temp[:5]

    return SearchRecommendationResponse(
        query=query_text,
        matched_item_id=matched_item_id,
        similar_items=similar_items,
        upsell_recommendations=upsell_items,
        is_ta_query=is_ta,
    )


@api_router.get("/item-recommendations/{item_id}", response_model=ItemRuleRecommendationResponse)
async def get_item_rule_recommendations(item_id: str):
    items_df = _get_items_df()
    item_map = {
        str(r.get("item_id", "")).strip(): r
        for r in items_df.to_dicts()
        if str(r.get("item_id", "")).strip()
    }

    if item_id not in item_map:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found")

    rule = _get_recommendation_rules().get(item_id)
    if not rule:
        return ItemRuleRecommendationResponse(
            target_item_id=item_id,
            item_type=None,
            has_rule=False,
            similar_items=[],
            upsell_recommendations=[],
        )

    similar_items: List[SearchSuggestedItem] = []
    for sid in rule.get("similar_items", []):
        row = item_map.get(str(sid).strip())
        if row:
            similar_items.append(_row_to_search_item(row))

    item_type = str(rule.get("type", "")).strip() or None
    upsell_items: List[UpsellSuggestion] = []

    if _is_ta_type(item_type):
        temp: List[UpsellSuggestion] = []
        for u in rule.get("upsell_recommendations", []):
            if not isinstance(u, dict):
                continue
            uid = str(u.get("item_id", "")).strip()
            if not uid or uid not in item_map:
                continue
            temp.append(
                UpsellSuggestion(
                    **_row_to_search_item(item_map[uid]).model_dump(),
                    size=(str(u.get("size")) if u.get("size") is not None else None),
                    score=_safe_score(u.get("score")),
                )
            )
        temp.sort(key=lambda x: x.score, reverse=True)
        upsell_items = temp[:5]

    return ItemRuleRecommendationResponse(
        target_item_id=item_id,
        item_type=item_type,
        has_rule=True,
        similar_items=similar_items,
        upsell_recommendations=upsell_items,
    )


@api_router.get("/items/{item_id}", response_model=ProductItem)
async def get_item_details(item_id: str):
    row = _get_items_df().filter((pl.col("item_id") == item_id) & (pl.col("sale_status") == 1))
    if row.height == 0:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found or unavailable")
    return _row_to_item(row.to_dicts()[0])


@api_router.get("/recommendations/{item_id}", response_model=RecommendationResponse)
async def get_recommendations(item_id: str):
    """
    Legacy endpoint (kept for compatibility):
    - Frequently bought together from transactions
    - Relevant by category/brand + price proximity
    """
    items_df = _get_items_df().filter(pl.col("sale_status") == 1)
    target_df = items_df.filter(pl.col("item_id") == item_id)

    if target_df.height == 0:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found or unavailable")

    target = target_df.to_dicts()[0]
    target_brand = str(target.get("brand", ""))
    target_category = str(target.get("category_l1", ""))
    target_price = float(target.get("price", 0.0) or 0.0)

    transactions_df = _get_transactions_df()
    customer_pool = transactions_df.filter(pl.col("item_id") == item_id).select("customer_id").unique()

    frequently_bought: List[RecommendedItem] = []
    if customer_pool.height > 0:
        companion_counts = (
            transactions_df.join(customer_pool, on="customer_id", how="inner")
            .filter(pl.col("item_id") != item_id)
            .group_by("item_id")
            .agg(pl.len().alias("frequency"))
            .sort("frequency", descending=True)
            .head(20)
        )

        fbt_df = (
            companion_counts.join(items_df, on="item_id", how="inner")
            .sort("frequency", descending=True)
            .head(5)
        )

        frequently_bought = [
            RecommendedItem(**_row_to_item(r).model_dump(), frequency=int(r.get("frequency", 0) or 0))
            for r in fbt_df.to_dicts()
        ]

    relevant_df = (
        items_df.filter(pl.col("item_id") != item_id)
        .with_columns(
            [
                (
                    pl.when(pl.col("category_l1") == target_category).then(2).otherwise(0)
                    + pl.when(pl.col("brand") == target_brand).then(1).otherwise(0)
                ).alias("relevance_score"),
                (pl.col("price") - pl.lit(target_price)).abs().alias("price_gap"),
            ]
        )
        .filter(pl.col("relevance_score") > 0)
        .sort(["relevance_score", "price_gap"], descending=[True, False])
        .head(5)
    )

    if relevant_df.height < 5:
        existing_ids = relevant_df.select("item_id").to_series().to_list() if relevant_df.height else []
        fallback_df = (
            items_df.filter((pl.col("item_id") != item_id) & (~pl.col("item_id").is_in(existing_ids)))
            .with_columns(
                [
                    pl.lit(0).alias("relevance_score"),
                    (pl.col("price") - pl.lit(target_price)).abs().alias("price_gap"),
                ]
            )
            .sort("price_gap")
            .head(5 - relevant_df.height)
        )
        relevant_df = pl.concat([relevant_df, fallback_df], how="vertical")

    relevant = [
        RecommendedItem(
            **_row_to_item(r).model_dump(),
            relevance_score=int(r.get("relevance_score", 0) or 0),
        )
        for r in relevant_df.to_dicts()
    ]

    return RecommendationResponse(
        target_item_id=item_id,
        frequently_bought_together=frequently_bought,
        relevant=relevant,
    )


# ==============================
# App setup
# ==============================
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)