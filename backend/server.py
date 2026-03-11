from pathlib import Path
from typing import Dict, List, Literal, Optional

import os
import logging
import polars as pl
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException, Query
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = Path("/app/data")
ITEMS_FILE = DATA_DIR / "items.parquet"
TRANSACTIONS_FILE = DATA_DIR / "transactions-2025-12.parquet"


app = FastAPI()
api_router = APIRouter(prefix="/api")


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


_cache: Dict[str, object] = {
    "items_df": None,
    "items_mtime": None,
    "transactions_df": None,
    "transactions_mtime": None,
}


def _first_existing(columns: List[str], candidates: List[str]) -> Optional[str]:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _normalized_items_df() -> pl.DataFrame:
    if not ITEMS_FILE.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Missing data file: {ITEMS_FILE}. Please add items.parquet to /app/data.",
        )

    raw_df = pl.read_parquet(ITEMS_FILE)
    columns = raw_df.columns

    item_id_col = _first_existing(columns, ["item_id", "itemId", "sku", "product_id", "id"])
    name_col = _first_existing(columns, ["name", "item_name", "product_name", "title"])
    brand_col = _first_existing(columns, ["brand", "brand_name", "manufacturer"])
    category_col = _first_existing(columns, ["category_l1", "category", "category_name", "department"])
    price_col = _first_existing(columns, ["price", "price_vnd", "sale_price", "selling_price"])
    sale_status_col = _first_existing(columns, ["sale_status", "status", "is_active", "available"])
    rating_col = _first_existing(columns, ["rating", "avg_rating", "stars"])

    required_cols = {
        "item_id": item_id_col,
        "name": name_col,
        "brand": brand_col,
        "category_l1": category_col,
        "price": price_col,
    }
    missing_fields = [field for field, col in required_cols.items() if col is None]
    if missing_fields:
        raise HTTPException(
            status_code=500,
            detail=f"items.parquet is missing required fields: {', '.join(missing_fields)}",
        )

    selection = [
        pl.col(item_id_col).cast(pl.Utf8).alias("item_id"),
        pl.col(name_col).cast(pl.Utf8).alias("name"),
        pl.col(brand_col).cast(pl.Utf8).alias("brand"),
        pl.col(category_col).cast(pl.Utf8).alias("category_l1"),
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
        raise HTTPException(
            status_code=500,
            detail=(
                f"Missing data file: {TRANSACTIONS_FILE}. "
                "Please add transactions-2025-12.parquet to /app/data."
            ),
        )

    raw_df = pl.read_parquet(TRANSACTIONS_FILE)
    columns = raw_df.columns

    customer_col = _first_existing(columns, ["customer_id", "user_id", "buyer_id"])
    item_id_col = _first_existing(columns, ["item_id", "itemId", "product_id", "sku"])

    if customer_col is None or item_id_col is None:
        raise HTTPException(
            status_code=500,
            detail=(
                "transactions-2025-12.parquet must include customer_id/user_id and "
                "item_id/product_id columns"
            ),
        )

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


@api_router.get("/")
async def root():
    return {"message": "Amazon-inspired recommendation API is live"}


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
        q_term = q.strip().lower()
        df = df.filter(
            pl.col("name").str.to_lowercase().str.contains(q_term, literal=True)
            | pl.col("brand").str.to_lowercase().str.contains(q_term, literal=True)
            | pl.col("item_id").str.to_lowercase().str.contains(q_term, literal=True)
            | pl.col("category_l1").str.to_lowercase().str.contains(q_term, literal=True)
        )

    if category.strip():
        category_term = category.strip().lower()
        df = df.filter(pl.col("category_l1").str.to_lowercase() == category_term)

    if brand.strip():
        brand_term = brand.strip().lower()
        df = df.filter(pl.col("brand").str.to_lowercase() == brand_term)

    total = df.height
    sorted_df = df.sort(sort_by, descending=(sort_dir == "desc"))
    paged_df = sorted_df.slice(offset, limit)

    return ProductCatalogResponse(
        total=total,
        items=[_row_to_item(row) for row in paged_df.to_dicts()],
    )


@api_router.get("/items/{item_id}", response_model=ProductItem)
async def get_item_details(item_id: str):
    item_df = _get_items_df().filter((pl.col("item_id") == item_id) & (pl.col("sale_status") == 1))
    if item_df.height == 0:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found or unavailable")
    return _row_to_item(item_df.to_dicts()[0])


@api_router.get("/recommendations/{item_id}", response_model=RecommendationResponse)
async def get_recommendations(item_id: str):
    items_df = _get_items_df().filter(pl.col("sale_status") == 1)
    target_df = items_df.filter(pl.col("item_id") == item_id)
    if target_df.height == 0:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found or unavailable")

    target_row = target_df.to_dicts()[0]
    target_brand = str(target_row.get("brand", ""))
    target_category = str(target_row.get("category_l1", ""))
    target_price = float(target_row.get("price", 0.0) or 0.0)

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

        frequently_bought_df = (
            companion_counts.join(items_df, on="item_id", how="inner")
            .sort("frequency", descending=True)
            .head(5)
        )

        frequently_bought = [
            RecommendedItem(**_row_to_item(row).model_dump(), frequency=int(row.get("frequency", 0) or 0))
            for row in frequently_bought_df.to_dicts()
        ]

    relevant_df = (
        items_df.filter(pl.col("item_id") != item_id)
        .with_columns(
            [
                (
                    pl.when(pl.col("category_l1") == target_category)
                    .then(2)
                    .otherwise(0)
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
        already_ids = relevant_df.select("item_id").to_series().to_list() if relevant_df.height else []
        fallback_df = (
            items_df.filter(
                (pl.col("item_id") != item_id)
                & (~pl.col("item_id").is_in(already_ids))
            )
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
            **_row_to_item(row).model_dump(),
            relevance_score=int(row.get("relevance_score", 0) or 0),
        )
        for row in relevant_df.to_dicts()
    ]

    return RecommendationResponse(
        target_item_id=item_id,
        frequently_bought_together=frequently_bought,
        relevant=relevant,
    )


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