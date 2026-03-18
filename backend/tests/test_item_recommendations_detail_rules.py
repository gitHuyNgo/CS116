"""Regression tests for /api/item-recommendations JSON-rule detail behavior."""

import json
import os
from pathlib import Path

import polars as pl
import pytest
import requests
from dotenv import load_dotenv


load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
RULES_FILE = Path("/app/data/recommendations_all.json")
ITEMS_FILE = Path("/app/data/items.parquet")
TA_VARIANTS = {"tã", "Tã", "tÃ", "TÃ"}


@pytest.fixture(scope="session")
def api_client():
    if not BASE_URL:
        pytest.skip("REACT_APP_BACKEND_URL is missing")
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="session")
def available_item_ids():
    if not ITEMS_FILE.exists():
        pytest.skip("items.parquet is missing")
    items_df = pl.read_parquet(str(ITEMS_FILE))
    for column_name in ["item_id", "itemId", "sku", "product_id", "id"]:
        if column_name in items_df.columns:
            ids = (
                items_df.select(pl.col(column_name).cast(pl.Utf8).alias("item_id"))
                .with_columns(pl.col("item_id").fill_null(""))
                .filter(pl.col("item_id") != "")
                .unique()
                .to_series()
                .to_list()
            )
            return set(ids)
    pytest.skip("No compatible item_id column found in items.parquet")


@pytest.fixture(scope="session")
def recommendation_rules():
    if not RULES_FILE.exists():
        pytest.skip("recommendations_all.json is missing")
    payload = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        pytest.skip("recommendations_all.json payload is not a list")

    indexed_rules = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        item_id = str(entry.get("item_id", "")).strip()
        if item_id:
            indexed_rules[item_id] = entry

    if not indexed_rules:
        pytest.skip("No valid recommendation rules found")
    return indexed_rules


@pytest.fixture(scope="session")
def ta_rule_item_id(recommendation_rules):
    for item_id, rule in recommendation_rules.items():
        if str(rule.get("type", "")).strip() in TA_VARIANTS:
            return item_id
    pytest.skip("No ta-type rule found")


@pytest.fixture(scope="session")
def non_ta_rule_item_id(recommendation_rules):
    for item_id, rule in recommendation_rules.items():
        if str(rule.get("type", "")).strip() not in TA_VARIANTS:
            return item_id
    pytest.skip("No non-ta rule found")


@pytest.fixture(scope="session")
def item_without_rule_id(available_item_ids, recommendation_rules):
    for item_id in available_item_ids:
        if item_id not in recommendation_rules:
            return item_id
    pytest.skip("No item found without recommendation rule")


# Module: /api/item-recommendations/{item_id} no-rule fallback behavior
def test_item_recommendations_returns_has_rule_false_when_rule_missing(api_client, item_without_rule_id):
    response = api_client.get(f"{BASE_URL}/api/item-recommendations/{item_without_rule_id}")
    assert response.status_code == 200
    data = response.json()

    assert data["target_item_id"] == item_without_rule_id
    assert data["has_rule"] is False
    assert data["item_type"] is None
    assert data["similar_items"] == []
    assert data["upsell_recommendations"] == []


# Module: /api/item-recommendations/{item_id} ta-type behavior (similar + top-5 upsell by score)
def test_item_recommendations_ta_type_returns_similar_and_top5_upsell_sorted(
    api_client,
    recommendation_rules,
    ta_rule_item_id,
    available_item_ids,
):
    rule = recommendation_rules[ta_rule_item_id]
    response = api_client.get(f"{BASE_URL}/api/item-recommendations/{ta_rule_item_id}")
    assert response.status_code == 200
    data = response.json()

    assert data["target_item_id"] == ta_rule_item_id
    assert data["has_rule"] is True
    assert data["item_type"] in TA_VARIANTS

    expected_similar_ids = [item_id for item_id in rule.get("similar_items", []) if str(item_id) in available_item_ids]
    actual_similar_ids = [item["item_id"] for item in data["similar_items"]]
    assert actual_similar_ids == expected_similar_ids

    expected_upsell = sorted(
        [
            rec
            for rec in rule.get("upsell_recommendations", [])
            if isinstance(rec, dict) and str(rec.get("item_id", "")) in available_item_ids
        ],
        key=lambda rec: float(rec.get("score", 0) or 0),
        reverse=True,
    )[:5]
    actual_upsell = data["upsell_recommendations"]

    assert len(actual_upsell) <= 5
    assert [row["item_id"] for row in actual_upsell] == [str(row["item_id"]) for row in expected_upsell]
    if len(actual_upsell) >= 2:
        assert all(actual_upsell[i]["score"] >= actual_upsell[i + 1]["score"] for i in range(len(actual_upsell) - 1))
    for row in actual_upsell:
        assert isinstance(row["name"], str) and row["name"].strip() != ""
        assert isinstance(row["price"], (int, float))
        assert "size" in row
        assert isinstance(row["score"], (int, float))


# Module: /api/item-recommendations/{item_id} non-ta behavior (similar only, no upsell)
def test_item_recommendations_non_ta_returns_similar_without_upsell(
    api_client,
    recommendation_rules,
    non_ta_rule_item_id,
    available_item_ids,
):
    rule = recommendation_rules[non_ta_rule_item_id]
    response = api_client.get(f"{BASE_URL}/api/item-recommendations/{non_ta_rule_item_id}")
    assert response.status_code == 200
    data = response.json()

    assert data["target_item_id"] == non_ta_rule_item_id
    assert data["has_rule"] is True
    assert data["item_type"] not in TA_VARIANTS

    expected_similar_ids = [item_id for item_id in rule.get("similar_items", []) if str(item_id) in available_item_ids]
    actual_similar_ids = [item["item_id"] for item in data["similar_items"]]
    assert actual_similar_ids == expected_similar_ids
    assert data["upsell_recommendations"] == []
