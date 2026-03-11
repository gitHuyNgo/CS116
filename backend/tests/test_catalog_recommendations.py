"""API regression tests for catalog listing, product detail, and recommendation flows."""

import os

import polars as pl
import pytest
import requests
from dotenv import load_dotenv


load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")

ITEMS_FILE = "/app/data/items.parquet"
TRANSACTIONS_FILE = "/app/data/transactions-2025-12.parquet"
TARGET_ITEM_ID = "000804000046"


def _first_existing(columns, candidates):
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


@pytest.fixture(scope="session")
def api_client():
    if not BASE_URL:
        pytest.skip("REACT_APP_BACKEND_URL is missing")
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="session")
def normalized_items_df():
    raw_df = pl.read_parquet(ITEMS_FILE)
    columns = raw_df.columns

    item_id_col = _first_existing(columns, ["item_id", "itemId", "sku", "product_id", "id"])
    name_col = _first_existing(columns, ["name", "item_name", "product_name", "title"])
    brand_col = _first_existing(columns, ["brand", "brand_name", "manufacturer"])
    category_col = _first_existing(columns, ["category_l1", "category", "category_name", "department"])
    price_col = _first_existing(columns, ["price", "price_vnd", "sale_price", "selling_price"])
    sale_status_col = _first_existing(columns, ["sale_status", "status", "is_active", "available"])

    if not all([item_id_col, name_col, brand_col, category_col, price_col]):
        pytest.skip("items.parquet missing expected columns for validation")

    selection = [
        pl.col(item_id_col).cast(pl.Utf8).alias("item_id"),
        pl.col(name_col).cast(pl.Utf8).alias("name"),
        pl.col(brand_col).cast(pl.Utf8).alias("brand"),
        pl.col(category_col).cast(pl.Utf8).alias("category_l1"),
        pl.col(price_col).cast(pl.Float64, strict=False).alias("price"),
        (pl.col(sale_status_col).cast(pl.Int64, strict=False).alias("sale_status") if sale_status_col else pl.lit(1).alias("sale_status")),
    ]

    return raw_df.select(selection).with_columns(
        [
            pl.col("item_id").fill_null(""),
            pl.col("name").fill_null(""),
            pl.col("brand").fill_null(""),
            pl.col("category_l1").fill_null(""),
            pl.col("price").fill_null(0.0),
            pl.col("sale_status").fill_null(0),
        ]
    )


@pytest.fixture(scope="session")
def normalized_tx_df():
    raw_df = pl.read_parquet(TRANSACTIONS_FILE)
    columns = raw_df.columns
    customer_col = _first_existing(columns, ["customer_id", "user_id", "buyer_id"])
    item_id_col = _first_existing(columns, ["item_id", "itemId", "product_id", "sku"])
    if not customer_col or not item_id_col:
        pytest.skip("transactions parquet missing customer/item columns")
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


def test_items_catalog_returns_only_sale_status_1(api_client, normalized_items_df):
    response = api_client.get(f"{BASE_URL}/api/items", params={"limit": 120, "offset": 0})
    assert response.status_code == 200
    data = response.json()
    assert "items" in data and isinstance(data["items"], list)
    assert all(item["sale_status"] == 1 for item in data["items"])


def test_items_catalog_search_sort_and_pagination(api_client):
    response = api_client.get(
        f"{BASE_URL}/api/items",
        params={"q": "tai nghe", "sort_by": "price", "sort_dir": "desc", "limit": 5, "offset": 0},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= len(data["items"])
    assert len(data["items"]) <= 5
    if len(data["items"]) >= 2:
        assert data["items"][0]["price"] >= data["items"][1]["price"]


def test_items_catalog_filter_by_category_and_brand(api_client):
    meta = api_client.get(f"{BASE_URL}/api/items/meta")
    assert meta.status_code == 200
    meta_data = meta.json()
    assert isinstance(meta_data.get("categories"), list)
    assert isinstance(meta_data.get("brands"), list)
    if not meta_data["categories"] or not meta_data["brands"]:
        pytest.skip("No categories or brands to validate filtering")

    category = meta_data["categories"][0]
    brand = meta_data["brands"][0]
    response = api_client.get(
        f"{BASE_URL}/api/items",
        params={"category": category, "brand": brand, "limit": 20, "offset": 0},
    )
    assert response.status_code == 200
    payload = response.json()
    for item in payload["items"]:
        assert item["category_l1"].lower() == category.lower()
        assert item["brand"].lower() == brand.lower()


def test_items_catalog_excludes_known_unavailable_item(api_client, normalized_items_df):
    unavailable = normalized_items_df.filter(pl.col("sale_status") != 1).select("item_id").head(1)
    if unavailable.height == 0:
        pytest.skip("No unavailable items in dataset to validate exclusion")

    unavailable_id = unavailable.to_dicts()[0]["item_id"]
    response = api_client.get(f"{BASE_URL}/api/items", params={"q": unavailable_id, "limit": 50, "offset": 0})
    assert response.status_code == 200
    returned_ids = {item["item_id"] for item in response.json()["items"]}
    assert unavailable_id not in returned_ids


def test_get_item_details_for_sale_status_1_item(api_client):
    response = api_client.get(f"{BASE_URL}/api/items/{TARGET_ITEM_ID}")
    assert response.status_code == 200
    data = response.json()
    assert data["item_id"] == TARGET_ITEM_ID
    assert data["sale_status"] == 1
    assert isinstance(data["name"], str) and data["name"].strip() != ""


def test_get_item_details_returns_404_for_unavailable_item(api_client, normalized_items_df):
    unavailable = normalized_items_df.filter(pl.col("sale_status") != 1).select("item_id").head(1)
    if unavailable.height == 0:
        pytest.skip("No unavailable item to verify 404 behavior")

    unavailable_id = unavailable.to_dicts()[0]["item_id"]
    response = api_client.get(f"{BASE_URL}/api/items/{unavailable_id}")
    assert response.status_code == 404


def test_recommendations_frequently_bought_matches_tx_frequency(api_client, normalized_items_df, normalized_tx_df):
    response = api_client.get(f"{BASE_URL}/api/recommendations/{TARGET_ITEM_ID}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["target_item_id"] == TARGET_ITEM_ID
    assert "frequently_bought_together" in payload

    active_ids = set(
        normalized_items_df.filter(pl.col("sale_status") == 1).select("item_id").to_series().to_list()
    )
    customer_pool = normalized_tx_df.filter(pl.col("item_id") == TARGET_ITEM_ID).select("customer_id").unique()
    expected = (
        normalized_tx_df.join(customer_pool, on="customer_id", how="inner")
        .filter(pl.col("item_id") != TARGET_ITEM_ID)
        .group_by("item_id")
        .agg(pl.len().alias("frequency"))
        .filter(pl.col("item_id").is_in(list(active_ids)))
        .sort("frequency", descending=True)
        .head(5)
    )
    expected_rows = expected.to_dicts()
    expected_freq_map = {row["item_id"]: int(row["frequency"]) for row in expected_rows}
    min_expected_frequency = min(expected_freq_map.values()) if expected_freq_map else 0

    actual = payload["frequently_bought_together"]
    assert all(item["item_id"] in expected_freq_map for item in actual)
    assert all(item["frequency"] == expected_freq_map[item["item_id"]] for item in actual)
    assert all(actual[idx]["frequency"] >= actual[idx + 1]["frequency"] for idx in range(len(actual) - 1))
    if actual:
        assert actual[-1]["frequency"] >= min_expected_frequency


def test_recommendations_relevant_stream_matches_category_brand_logic(api_client, normalized_items_df):
    response = api_client.get(f"{BASE_URL}/api/recommendations/{TARGET_ITEM_ID}")
    assert response.status_code == 200
    payload = response.json()
    relevant = payload["relevant"]
    assert isinstance(relevant, list)
    assert len(relevant) <= 5

    target = normalized_items_df.filter(pl.col("item_id") == TARGET_ITEM_ID).to_dicts()[0]
    matching_pool = normalized_items_df.filter(
        (pl.col("item_id") != TARGET_ITEM_ID)
        & (pl.col("sale_status") == 1)
        & ((pl.col("category_l1") == target["category_l1"]) | (pl.col("brand") == target["brand"]))
    )

    if matching_pool.height >= 5:
        assert all((item["category_l1"] == target["category_l1"]) or (item["brand"] == target["brand"]) for item in relevant)
    else:
        assert any((item["category_l1"] == target["category_l1"]) or (item["brand"] == target["brand"]) for item in relevant)


def test_recommendations_only_returns_sale_status_1_items(api_client):
    response = api_client.get(f"{BASE_URL}/api/recommendations/{TARGET_ITEM_ID}")
    assert response.status_code == 200
    payload = response.json()
    all_recos = payload["frequently_bought_together"] + payload["relevant"]
    assert all(item["sale_status"] == 1 for item in all_recos)
