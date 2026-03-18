"""Regression tests for JSON-driven search recommendations and ta-variant branching."""

import json
import os
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv


load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
RULES_FILE = Path("/app/data/recommendations_all.json")


@pytest.fixture(scope="session")
def api_client():
    if not BASE_URL:
        pytest.skip("REACT_APP_BACKEND_URL is missing")
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="session")
def recommendation_rules():
    if not RULES_FILE.exists():
        pytest.skip("recommendations_all.json is missing")
    payload = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        pytest.skip("recommendations_all.json payload is not list")
    indexed = {}
    for entry in payload:
        if isinstance(entry, dict) and str(entry.get("item_id", "")).strip():
            indexed[str(entry["item_id"]).strip()] = entry
    if not indexed:
        pytest.skip("recommendations_all.json has no valid entries")
    return indexed


@pytest.fixture(scope="session")
def rule_backed_item_id(api_client, recommendation_rules):
    for item_id in recommendation_rules:
        response = api_client.get(f"{BASE_URL}/api/search-recommendations", params={"q": item_id})
        if response.status_code != 200:
            continue
        payload = response.json()
        if payload.get("matched_item_id") == item_id:
            return item_id
    pytest.skip("No recommendation rule item_id is searchable in current dataset")


# Module: /api/search-recommendations (matched item id + similar items from recommendations_all.json)
def test_search_recommendations_returns_similar_items_from_json_rules(api_client, recommendation_rules, rule_backed_item_id):
    response = api_client.get(f"{BASE_URL}/api/search-recommendations", params={"q": rule_backed_item_id})
    assert response.status_code == 200
    data = response.json()

    assert data["query"] == rule_backed_item_id
    assert data["matched_item_id"] == rule_backed_item_id
    assert isinstance(data["similar_items"], list)

    expected_similar = recommendation_rules[rule_backed_item_id].get("similar_items", [])
    actual_similar_ids = [item["item_id"] for item in data["similar_items"]]
    assert actual_similar_ids == expected_similar

    for item in data["similar_items"]:
        assert isinstance(item["name"], str) and item["name"].strip() != ""
        assert isinstance(item["price"], (int, float))
        assert "sale_status" in item


# Module: ta-variant behavior (upsell sorted desc and top 5)
def test_ta_variant_query_returns_top_5_upsell_sorted_desc(api_client, recommendation_rules):
    response = api_client.get(f"{BASE_URL}/api/search-recommendations", params={"q": "tã"})
    assert response.status_code == 200
    data = response.json()

    assert data["is_ta_query"] is True
    assert data["matched_item_id"] is not None

    matched_rule = recommendation_rules.get(data["matched_item_id"])
    assert matched_rule is not None

    expected_upsell = sorted(
        [entry for entry in matched_rule.get("upsell_recommendations", []) if isinstance(entry, dict)],
        key=lambda row: float(row.get("score", 0) or 0),
        reverse=True,
    )[:5]

    actual_upsell = data["upsell_recommendations"]
    assert len(actual_upsell) <= 5

    expected_ids = [row["item_id"] for row in expected_upsell]
    actual_ids = [row["item_id"] for row in actual_upsell]
    assert actual_ids == expected_ids

    if len(actual_upsell) >= 2:
        assert all(actual_upsell[i]["score"] >= actual_upsell[i + 1]["score"] for i in range(len(actual_upsell) - 1))

    for item in actual_upsell:
        assert isinstance(item["name"], str) and item["name"].strip() != ""
        assert isinstance(item["price"], (int, float))
        assert "size" in item
        assert isinstance(item["score"], (int, float))
        assert "sale_status" in item


# Module: non-ta behavior (similar only, no upsell list)
def test_non_ta_query_hides_upsell_even_if_rule_has_upsell(api_client, recommendation_rules, rule_backed_item_id):
    response = api_client.get(f"{BASE_URL}/api/search-recommendations", params={"q": rule_backed_item_id})
    assert response.status_code == 200
    data = response.json()

    assert data["is_ta_query"] is False
    assert data["matched_item_id"] == rule_backed_item_id
    assert isinstance(data["similar_items"], list)
    assert len(data["similar_items"]) == len(recommendation_rules[rule_backed_item_id].get("similar_items", []))
    assert data["upsell_recommendations"] == []


# Module: ta-variant exact list supports all requested variants
@pytest.mark.parametrize("ta_variant", ["tã", "Tã", "tÃ", "TÃ"])
def test_all_ta_variants_mark_query_as_ta(api_client, ta_variant):
    response = api_client.get(f"{BASE_URL}/api/search-recommendations", params={"q": ta_variant})
    assert response.status_code == 200
    data = response.json()
    assert data["is_ta_query"] is True


# Module: unmatched search should return empty recommendation payload safely
def test_unmatched_query_returns_empty_payload(api_client):
    response = api_client.get(
        f"{BASE_URL}/api/search-recommendations",
        params={"q": "zzzz_no_match_term_12345"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["matched_item_id"] is None
    assert data["similar_items"] == []
    assert data["upsell_recommendations"] == []
