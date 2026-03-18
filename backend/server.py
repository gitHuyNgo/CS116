from pathlib import Path
from typing import Dict, List, Literal, Optional

import os
import logging
import polars as pl
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException, Query
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware


ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = ROOT_DIR.parent / "data"
ITEMS_FILE       = DATA_DIR / "items.parquet"
TRANSACTIONS_FILE = DATA_DIR / "transactions-2025-12.parquet"

app = FastAPI()
api_router = APIRouter(prefix="/api")

# ============================================================
# CONFIG
# ============================================================
TOP_K      = 10
MAX_BASKET = 20
SIZE_ORDER = {"NB": 1, "S": 2, "M": 3, "L": 4, "XL": 5, "XXL": 6, "XXXL": 7}
DEDUP_KEYS = ["item_id", "category", "price"]


# ============================================================
# SCHEMAS
# ============================================================
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


class UpsellItem(BaseModel):
    item_id: str
    size: Optional[str] = None
    score: int


class RecommendationResponse(BaseModel):
    item_id: str
    type: str                          # "tã" | "non-tã"
    similar_items: List[str]
    upsell_recommendations: List[UpsellItem]


# ============================================================
# FILE-LEVEL CACHE
# ============================================================
_cache: Dict[str, object] = {
    "items_df":         None,
    "items_mtime":      None,
    "cobuy_matrix":     None,
    "cobuy_mtime":      None,
}


# ============================================================
# DATA LOADING & ENRICHMENT
# ============================================================
def _load_items() -> pl.DataFrame:
    if not ITEMS_FILE.exists():
        raise HTTPException(status_code=500, detail=f"Missing: {ITEMS_FILE}")

    return (
        pl.read_parquet(ITEMS_FILE)
        .filter(pl.col("sale_status") == 1)
        .with_columns([
            # Parse size token từ description
            pl.col("description")
                .str.extract(r"(?i)(NB|XXXL|XXL|XL|S|M|L)", 1)
                .str.to_uppercase()
                .alias("_size_from_desc"),
            # Parse size token từ cột size
            pl.col("size")
                .str.extract(r"(?i)(NB|XXXL|XXL|XL|S|M|L)", 1)
                .str.to_uppercase()
                .alias("_size_from_col"),
        ])
        .with_columns([
            # size_list: desc → size col → NULL
            pl.when(pl.col("_size_from_desc").is_not_null())
                .then(pl.col("_size_from_desc"))
                .when(pl.col("_size_from_col").is_not_null())
                .then(pl.col("_size_from_col"))
                .otherwise(None)
                .alias("size_list"),
        ])
        .drop(["_size_from_desc", "_size_from_col"])
        .unique(subset=DEDUP_KEYS, keep="first", maintain_order=True)
    )


def _load_transactions() -> pl.DataFrame:
    if not TRANSACTIONS_FILE.exists():
        raise HTTPException(status_code=500, detail=f"Missing: {TRANSACTIONS_FILE}")
    return pl.read_parquet(TRANSACTIONS_FILE).select([
        pl.col("customer_id").cast(pl.Utf8),
        pl.col("item_id").cast(pl.Utf8),
    ]).filter(
        (pl.col("customer_id") != "") & (pl.col("item_id") != "")
    )


def _get_items() -> pl.DataFrame:
    mtime = ITEMS_FILE.stat().st_mtime if ITEMS_FILE.exists() else None
    if _cache["items_df"] is None or _cache["items_mtime"] != mtime:
        _cache["items_df"]    = _load_items()
        _cache["items_mtime"] = mtime
    return _cache["items_df"]


def _get_cobuy_matrix(items_df: pl.DataFrame) -> pl.DataFrame:
    """Co-occurrence matrix — rebuilt khi file transaction thay đổi."""
    mtime = TRANSACTIONS_FILE.stat().st_mtime if TRANSACTIONS_FILE.exists() else None
    if _cache["cobuy_matrix"] is not None and _cache["cobuy_mtime"] == mtime:
        return _cache["cobuy_matrix"]

    transactions = _load_transactions()
    valid_ids = items_df["item_id"].to_list()

    basket = (
        transactions
        .group_by("customer_id")
        .agg(pl.col("item_id").unique().alias("items"))
        .with_columns(pl.col("items").list.head(MAX_BASKET))
        .filter(pl.col("items").list.len() >= 2)
    )

    basket_a = basket.lazy().explode("items").rename({"items": "item_a"})
    basket_b = basket.lazy().explode("items").rename({"items": "item_b"})

    co_occur = (
        basket_a
        .join(basket_b, on="customer_id")
        .filter(pl.col("item_a") < pl.col("item_b"))
        .group_by(["item_a", "item_b"])
        .agg(pl.len().alias("freq"))
        .collect()
    )

    mirror = co_occur.select([
        pl.col("item_b").alias("item_a"),
        pl.col("item_a").alias("item_b"),
        pl.col("freq"),
    ])
    matrix = (
        pl.concat([co_occur, mirror])
        .filter(
            pl.col("item_a").is_in(valid_ids) &
            pl.col("item_b").is_in(valid_ids)
        )
    )

    _cache["cobuy_matrix"] = matrix
    _cache["cobuy_mtime"]  = mtime
    return matrix


# ============================================================
# RECOMMENDATION LOGIC
# ============================================================
def _get_upsell(items_df: pl.DataFrame, query_id: str, is_ta: bool) -> List[UpsellItem]:
    """
    Upsell: cùng category, size >= size hiện tại.
    Nếu is_ta → chỉ tìm trong category_l1 == "Tã".
    Score: cùng size=8, size lớn hơn=20.
    """
    try:
        target = items_df.filter(pl.col("item_id") == query_id).row(0, named=True)
    except Exception:
        return []

    q_size_val = SIZE_ORDER.get(target["size_list"] or "", 0)
    q_cat      = target["category"]

    size_map_expr = (
        pl.col("size_list")
        .replace_strict(SIZE_ORDER, default=0)
        .fill_null(0)
    )

    # Tã: restrict toàn bộ category_l1 == "Tã"; non-Tã: cùng leaf category
    cat_filter = (
        pl.col("category_l1").str.to_lowercase() == "tã"
    ) if is_ta else (
        pl.col("category") == q_cat
    )

    candidates = items_df.filter(
        (pl.col("item_id") != query_id)
        & cat_filter
        & (size_map_expr >= q_size_val)
    )

    q_size = target["size_list"]
    same_size_expr = (
        pl.col("size_list").is_null() & pl.lit(q_size is None)
    ) if q_size is None else (
        pl.col("size_list") == q_size
    )

    scored = candidates.with_columns([
        pl.when(same_size_expr).then(pl.lit(8))
        .when(size_map_expr > q_size_val).then(pl.lit(20))
        .otherwise(pl.lit(1))
        .alias("upsale_score")
    ]).sort("upsale_score", descending=True).head(TOP_K)

    return [
        UpsellItem(
            item_id=row["item_id"],
            size=row["size_list"],
            score=row["upsale_score"],
        )
        for row in scored.iter_rows(named=True)
    ]


def _get_similar(
    items_df: pl.DataFrame,
    cobuy_matrix: pl.DataFrame,
    query_id: str,
    is_ta: bool,
) -> List[str]:
    """
    Similar hybrid:
      Non-Tã: final_score = freq * cat_score  (l3=3, l2=2)
      Tã:     final_score = freq * upsale_score (cùng size=8, size lớn hơn=20)
    freq=0 → score=0 → xếp cuối.
    """
    try:
        target = items_df.filter(pl.col("item_id") == query_id).row(0, named=True)
    except Exception:
        return []

    cobuy_q = (
        cobuy_matrix
        .filter(pl.col("item_a") == query_id)
        .select(["item_b", "freq"])
        .rename({"item_b": "item_id"})
    )

    q_l3 = target.get("category_l3")
    q_l2 = target.get("category_l2")

    # Tã: restrict toàn bộ candidates vào category_l1 == "Tã" trước
    # Non-Tã: tìm theo l3/l2 trong toàn catalog (Tã vẫn xuất hiện nếu match)
    base_filter = (
        (pl.col("item_id") != query_id)
        & (pl.col("category_l1").str.to_lowercase() == "tã")
        & (
            (pl.col("category_l3") == q_l3) |
            (pl.col("category_l2") == q_l2)
        )
    ) if is_ta else (
        (pl.col("item_id") != query_id)
        & (
            (pl.col("category_l3") == q_l3) |
            (pl.col("category_l2") == q_l2)
        )
    )

    candidates = items_df.filter(base_filter).with_columns(
        pl.when(pl.col("category_l3") == q_l3)
            .then(pl.lit(3))
            .otherwise(pl.lit(2))
            .alias("cat_score")
    ).join(cobuy_q, on="item_id", how="left").with_columns(
        pl.col("freq").fill_null(0)
    )

    if not is_ta:
        scored = candidates.with_columns(
            (pl.col("freq") * pl.col("cat_score")).alias("final_score")
        )
    else:
        q_size_val = SIZE_ORDER.get(target.get("size_list") or "", 0)
        size_map_expr = (
            pl.col("size_list")
            .replace_strict(SIZE_ORDER, default=0)
            .fill_null(0)
        )
        t_size = target.get("size_list")
        same_size_expr = (
            pl.col("size_list").is_null() & pl.lit(t_size is None)
        ) if t_size is None else (
            pl.col("size_list") == t_size
        )
        scored = candidates.with_columns(
            pl.when(same_size_expr).then(pl.lit(8))
            .when(size_map_expr > q_size_val).then(pl.lit(20))
            .otherwise(pl.lit(1))
            .alias("upsale_score")
        ).with_columns(
            (pl.col("freq") * pl.col("upsale_score")).alias("final_score")
        )

    return (
        scored
        .sort("final_score", descending=True)
        .head(TOP_K)
        ["item_id"]
        .to_list()
    )


# ============================================================
# HELPERS
# ============================================================
def _row_to_item(row: Dict) -> ProductItem:
    return ProductItem(
        item_id=str(row.get("item_id", "")),
        name=str(row.get("category", "Unknown")),   # name = category per schema
        brand=str(row.get("brand", "Unknown brand")),
        category_l1=str(row.get("category_l1", "Uncategorized")),
        price=float(row.get("price", 0.0) or 0.0),
        sale_status=int(row.get("sale_status", 0) or 0),
        rating=float(row["rating"]) if row.get("rating") is not None else None,
    )


# ============================================================
# ROUTES
# ============================================================
@api_router.get("/")
async def root():
    return {"message": "Recommendation API is live"}


@api_router.get("/items/meta", response_model=ProductFiltersResponse)
async def list_filter_metadata():
    df = _get_items()
    return ProductFiltersResponse(
        categories=df.select("category_l1").drop_nulls().unique().sort("category_l1")
                     .to_series().to_list(),
        brands=df.select("brand").drop_nulls().unique().sort("brand")
                  .to_series().to_list(),
    )


@api_router.get("/items", response_model=ProductCatalogResponse)
async def list_items(
    q: str = Query(default="", max_length=120),
    category: str = Query(default="", max_length=120),
    brand: str = Query(default="", max_length=120),
    sort_by: Literal["category", "price", "brand", "item_id"] = "category",
    sort_dir: Literal["asc", "desc"] = "asc",
    limit: int = Query(default=24, ge=1, le=120),
    offset: int = Query(default=0, ge=0),
):
    df = _get_items()

    if q.strip():
        t = q.strip().lower()
        # Nếu query chứa "tã" → chỉ search trong category_l1 == "Tã"
        # Ngược lại → search toàn catalog (Tã vẫn có thể xuất hiện nếu match)
        if "tã" in t:
            df = df.filter(pl.col("category_l1").str.to_lowercase() == "tã")
        else:
            df = df.filter(
                pl.col("category").str.to_lowercase().str.contains(t, literal=True)
                | pl.col("brand").str.to_lowercase().str.contains(t, literal=True)
                | pl.col("item_id").str.to_lowercase().str.contains(t, literal=True)
                | pl.col("category_l1").str.to_lowercase().str.contains(t, literal=True)
            )
    if category.strip():
        df = df.filter(pl.col("category_l1").str.to_lowercase() == category.strip().lower())
    if brand.strip():
        df = df.filter(pl.col("brand").str.to_lowercase() == brand.strip().lower())

    total = df.height
    paged = df.sort(sort_by, descending=(sort_dir == "desc")).slice(offset, limit)
    return ProductCatalogResponse(total=total, items=[_row_to_item(r) for r in paged.to_dicts()])


@api_router.get("/items/{item_id}", response_model=ProductItem)
async def get_item(item_id: str):
    row = _get_items().filter(pl.col("item_id") == item_id)
    if row.height == 0:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found")
    return _row_to_item(row.to_dicts()[0])


@api_router.get("/recommendations/{item_id}", response_model=RecommendationResponse)
async def get_recommendations(item_id: str):
    items_df = _get_items()

    target_df = items_df.filter(pl.col("item_id") == item_id)
    if target_df.height == 0:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found")

    target  = target_df.row(0, named=True)
    is_ta   = (target.get("category_l1") or "").strip() == "Tã"
    item_type = "tã" if is_ta else "non-tã"

    cobuy_matrix  = _get_cobuy_matrix(items_df)
    similar_items = _get_similar(items_df, cobuy_matrix, item_id, is_ta)
    upsell        = _get_upsell(items_df, item_id, is_ta) if is_ta else []

    return RecommendationResponse(
        item_id=item_id,
        type=item_type,
        similar_items=similar_items,
        upsell_recommendations=upsell,
    )


# ============================================================
# APP SETUP
# ============================================================
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