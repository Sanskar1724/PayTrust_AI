"""Per-category and per-merchant daily limits (per agent)."""
from __future__ import annotations

from app.domain.policy import DEFAULT_RULES, evaluate_policy
from tests.conftest import payment

# Seeded merchants: 1 TechMart Electronics (electronics), 2 BookHaven (books), 3 TravelEase (travel), ...
POLICY = {"user_id": 1, "agent_id": 1, "daily_limit": 100_000, "max_transaction": 60_000,
          "approval_threshold": 30_000, "allowed_categories": ["electronics", "books", "travel"],
          "blocked_categories": ["gambling", "financial_products"]}
BOOKS = {"merchant_id": 2, "merchant_name": "BookHaven", "category": "books"}


def _pay(**kw):
    return {"amount": 2_000, "category": "books", "merchant_id": 2, "merchant_name": "BookHaven",
            "merchant_category": "books"} | kw


# ── Engine ──

def test_category_limit_uses_the_merchants_registered_category():
    rules = {**DEFAULT_RULES.summary(), "category_limits": {"books": 5_000}}
    ok = evaluate_policy(rules, _pay(), scoped_spend={"category": 3_000, "merchant": 3_000})
    assert ok["authorized"]
    over = evaluate_policy(rules, _pay(), scoped_spend={"category": 3_001, "merchant": 0})
    assert over["violations"] == ["category_limit_exceeded"]
    assert over["reasons"][0].startswith("Daily limit for 'books' INR 5,000 exceeded")
    # The agent calls it "electronics", but the merchant is registered as books: the books limit applies.
    relabelled = evaluate_policy(rules, _pay(category="electronics"), scoped_spend={"category": 4_000, "merchant": 0})
    assert "category_limit_exceeded" in relabelled["violations"]


def test_merchant_limit_by_id_or_name_takes_the_strictest():
    rules = {**DEFAULT_RULES.summary(), "merchant_limits": {"bookhaven": 10_000, "2": 4_000}}
    over = evaluate_policy(rules, _pay(), scoped_spend={"category": 0, "merchant": 2_500})
    assert over["violations"] == ["merchant_limit_exceeded"]  # 2,500 + 2,000 > 4,000 (the id-keyed cap)
    other = evaluate_policy(rules, _pay(merchant_id=1, merchant_name="TechMart Electronics", category="electronics",
                                        merchant_category="electronics"), scoped_spend={"category": 0, "merchant": 0})
    assert other["authorized"]


def test_no_scoped_limits_means_no_scoped_checks():
    assert evaluate_policy(DEFAULT_RULES, _pay(), scoped_spend={"category": 10**7, "merchant": 10**7})["authorized"]


# ── Through the API ──

def test_category_limit_through_the_api(client, agent_key, admin_headers):
    assert client.put("/v1/policies", json=POLICY | {"category_limits": {"books": 3_000}},
                      headers=admin_headers).status_code == 200
    first = client.post("/v1/payments", json=payment(amount=2_000, description="novel", **BOOKS),
                        headers=agent_key).json()
    assert first["decision"] == "ALLOW"
    second = client.post("/v1/payments", json=payment(amount=1_500, description="textbook", **BOOKS),
                         headers=agent_key).json()
    assert second["policy_result"]["violations"] == ["category_limit_exceeded"]
    assert second["policy_result"]["spend"]["scoped_today"] == {"category": 2_000, "merchant": 2_000}
    gadget = client.post("/v1/payments", json=payment(amount=5_000), headers=agent_key).json()
    assert gadget["decision"] == "ALLOW"  # electronics has no category limit


def test_relabelling_a_purchase_does_not_dodge_the_category_limit(client, agent_key, admin_headers):
    client.put("/v1/policies", json=POLICY | {"category_limits": {"books": 3_000}}, headers=admin_headers)
    client.post("/v1/payments", json=payment(amount=2_500, description="novel", **BOOKS), headers=agent_key)
    sneaky = client.post("/v1/payments", json=payment(amount=1_000, description="more books",
                                                      **(BOOKS | {"category": "electronics"})),
                         headers=agent_key).json()
    assert "category_limit_exceeded" in sneaky["policy_result"]["violations"]


def test_merchant_limit_through_the_api_matches_names_case_insensitively(client, agent_key, admin_headers):
    resp = client.put("/v1/policies", json=POLICY | {"merchant_limits": {"techmart electronics": 5_000}},
                      headers=admin_headers)
    assert resp.status_code == 200
    assert client.post("/v1/payments", json=payment(amount=4_000), headers=agent_key).json()["decision"] == "ALLOW"
    over = client.post("/v1/payments", json=payment(amount=1_500, description="cable"), headers=agent_key).json()
    assert over["policy_result"]["violations"] == ["merchant_limit_exceeded"]
    elsewhere = client.post("/v1/payments", json=payment(amount=1_500, description="book", **BOOKS),
                            headers=agent_key).json()
    assert elsewhere["decision"] == "ALLOW"


def test_approval_recheck_honours_a_new_merchant_limit(client, agent_key, admin_headers):
    pending = client.post("/v1/payments", json=payment(amount=40_000), headers=agent_key).json()
    assert pending["status"] == "PENDING_APPROVAL"
    client.put("/v1/policies", json=POLICY | {"merchant_limits": {"1": 30_000}}, headers=admin_headers)
    resp = client.post(f"/v1/payments/{pending['request_id']}/approve", headers=admin_headers)
    assert resp.status_code == 409 and "Daily limit at 'TechMart Electronics'" in resp.text


def test_scoped_limit_validation(client, admin_headers):
    def put(extra):
        return client.put("/v1/policies", json=POLICY | extra, headers=admin_headers)

    assert put({"category_limits": {"spaceships": 100}}).status_code == 422          # unknown category
    assert put({"category_limits": {"books": -1}}).status_code == 422                 # negative
    assert put({"category_limits": {"books": True}}).status_code == 422               # not an amount
    assert put({"category_limits": {"Books": 1, "books ": 2}}).status_code == 422     # same category twice
    assert put({"merchant_limits": {" ": 100}}).status_code == 422                    # empty key
    saved = put({"category_limits": {"Books": 3_000}, "merchant_limits": {"GadgetHub": 10_000}})
    assert saved.status_code == 200
    assert saved.json()["category_limits"] == {"books": 3_000}                      # normalised
    cleared = put({"category_limits": {}, "merchant_limits": None})
    assert cleared.json()["category_limits"] is None and cleared.json()["merchant_limits"] is None
