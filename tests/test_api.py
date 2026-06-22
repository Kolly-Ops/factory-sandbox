"""
Tests covering the business logic contracts documented in
docs/api-business-logic.md and in each route's docstring.
"""
import importlib
import sys
import pytest


@pytest.fixture(autouse=True)
def fresh_app():
    if "app" in sys.modules:
        del sys.modules["app"]
    module = importlib.import_module("app")
    yield module
    if "app" in sys.modules:
        del sys.modules["app"]


@pytest.fixture()
def client(fresh_app):
    fresh_app.app.config["TESTING"] = True
    with fresh_app.app.test_client() as c:
        yield c


def _auth(role="service"):
    tokens = {
        "service": "service-token",
        "co-ceo": "co-ceo-token",
        "user": "user-token",
    }
    return {"Authorization": f"Bearer {tokens[role]}"}


# ---------------------------------------------------------------------------
# GET /healthz
# ---------------------------------------------------------------------------

class TestHealthz:
    def test_200_always(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.get_json() == {"status": "ok"}

    def test_no_auth_needed(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200

    def test_query_params_ignored(self, client):
        r = client.get("/healthz?foo=bar")
        assert r.status_code == 200
        assert r.get_json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# GET /budgets
# ---------------------------------------------------------------------------

class TestListBudgets:
    def test_200_with_valid_token(self, client):
        r = client.get("/budgets", headers=_auth("user"))
        assert r.status_code == 200
        data = r.get_json()
        assert "lanes" in data
        lanes = {lane["lane"]: lane for lane in data["lanes"]}
        assert set(lanes.keys()) == {"anthropic", "openai", "google"}
        assert lanes["anthropic"]["cap_usd"] == 500
        assert lanes["openai"]["cap_usd"] == 300
        assert lanes["google"]["cap_usd"] == 400

    def test_401_missing_token(self, client):
        r = client.get("/budgets")
        assert r.status_code == 401

    def test_401_invalid_token(self, client):
        r = client.get("/budgets", headers={"Authorization": "Bearer bad"})
        assert r.status_code == 401

    def test_service_token_accepted(self, client):
        r = client.get("/budgets", headers=_auth("service"))
        assert r.status_code == 200

    def test_lane_object_fields_present(self, client):
        r = client.get("/budgets", headers=_auth("user"))
        lane = r.get_json()["lanes"][0]
        for field in ("lane", "cap_usd", "spend_usd", "alert_threshold", "alert_fired"):
            assert field in lane


# ---------------------------------------------------------------------------
# GET /budgets/<lane>
# ---------------------------------------------------------------------------

class TestGetBudget:
    def test_200_known_lane(self, client):
        r = client.get("/budgets/anthropic", headers=_auth("user"))
        assert r.status_code == 200
        data = r.get_json()
        assert data["lane"] == "anthropic"
        assert data["cap_usd"] == 500

    def test_404_unknown_lane(self, client):
        r = client.get("/budgets/unknown", headers=_auth("user"))
        assert r.status_code == 404
        assert "lane not found" in r.get_json()["error"]

    def test_401_no_token(self, client):
        r = client.get("/budgets/anthropic")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /budgets/<lane>/spend
# ---------------------------------------------------------------------------

class TestRecordSpend:
    def _spend(self, client, lane="anthropic", amount=10.0, request_id="req-1"):
        return client.post(
            f"/budgets/{lane}/spend",
            json={"amount": amount, "request_id": request_id},
            headers=_auth("service"),
        )

    def test_200_valid_spend(self, client):
        r = self._spend(client)
        assert r.status_code == 200
        data = r.get_json()
        assert data["recorded"] == 10.0
        assert data["total_spend"] == 10.0
        assert data["idempotent_replay"] is False

    def test_401_no_token(self, client):
        r = client.post("/budgets/anthropic/spend", json={"amount": 1, "request_id": "r"})
        assert r.status_code == 401

    def test_403_wrong_role(self, client):
        r = client.post(
            "/budgets/anthropic/spend",
            json={"amount": 1, "request_id": "r"},
            headers=_auth("user"),
        )
        assert r.status_code == 403

    def test_404_unknown_lane(self, client):
        r = self._spend(client, lane="unknown")
        assert r.status_code == 404

    def test_422_missing_amount(self, client):
        r = client.post(
            "/budgets/anthropic/spend",
            json={"request_id": "r"},
            headers=_auth("service"),
        )
        assert r.status_code == 422

    def test_422_zero_amount(self, client):
        r = self._spend(client, amount=0)
        assert r.status_code == 422

    def test_422_negative_amount(self, client):
        r = self._spend(client, amount=-5)
        assert r.status_code == 422

    def test_422_missing_request_id(self, client):
        r = client.post(
            "/budgets/anthropic/spend",
            json={"amount": 5.0},
            headers=_auth("service"),
        )
        assert r.status_code == 422

    def test_idempotency_replay(self, client):
        self._spend(client, amount=10.0, request_id="dup")
        r2 = self._spend(client, amount=10.0, request_id="dup")
        assert r2.status_code == 200
        data = r2.get_json()
        assert data["idempotent_replay"] is True
        assert data["total_spend"] == 10.0

    def test_402_cap_exceeded(self, client):
        self._spend(client, amount=490.0, request_id="r1")
        r = self._spend(client, amount=20.0, request_id="r2")
        assert r.status_code == 402
        body = r.get_json()
        assert body["error"] == "budget cap exceeded"
        assert body["cap_usd"] == 500

    def test_cap_not_mutated_on_402(self, client):
        self._spend(client, amount=490.0, request_id="r1")
        self._spend(client, amount=20.0, request_id="r2")
        r = client.get("/budgets/anthropic", headers=_auth("user"))
        assert r.get_json()["spend_usd"] == 490.0

    def test_alert_fires_at_80_percent(self, client):
        r = self._spend(client, amount=400.0, request_id="r1")
        assert r.get_json()["alert_fired"] is True

    def test_alert_fires_only_once(self, client):
        self._spend(client, amount=400.0, request_id="r1")
        r2 = self._spend(client, amount=10.0, request_id="r2")
        assert r2.get_json()["alert_fired"] is False

    def test_below_alert_threshold(self, client):
        r = self._spend(client, amount=100.0, request_id="r1")
        assert r.get_json()["alert_fired"] is False


# ---------------------------------------------------------------------------
# POST /org/gates/<gate_id>/decide
# ---------------------------------------------------------------------------

class TestDecideGate:
    def _decide(self, client, gate_id="gate-1", decision="approved",
                 rationale="looks good", create_if_missing=True):
        return client.post(
            f"/org/gates/{gate_id}/decide",
            json={
                "decision": decision,
                "rationale": rationale,
                "create_if_missing": create_if_missing,
            },
            headers=_auth("co-ceo"),
        )

    def test_200_approve(self, client):
        r = self._decide(client)
        assert r.status_code == 200
        data = r.get_json()
        assert data["decision"] == "approved"
        assert data["event"] == "gate.decided"
        assert data["idempotent_replay"] is False

    def test_200_reject(self, client):
        r = self._decide(client, decision="rejected")
        assert r.status_code == 200
        assert r.get_json()["decision"] == "rejected"

    def test_401_no_token(self, client):
        r = client.post("/org/gates/g1/decide", json={"decision": "approved", "rationale": "ok"})
        assert r.status_code == 401

    def test_403_wrong_role(self, client):
        r = client.post(
            "/org/gates/g1/decide",
            json={"decision": "approved", "rationale": "ok", "create_if_missing": True},
            headers=_auth("service"),
        )
        assert r.status_code == 403

    def test_422_bad_decision(self, client):
        r = client.post(
            "/org/gates/g1/decide",
            json={"decision": "maybe", "rationale": "ok", "create_if_missing": True},
            headers=_auth("co-ceo"),
        )
        assert r.status_code == 422

    def test_422_missing_rationale(self, client):
        r = client.post(
            "/org/gates/g1/decide",
            json={"decision": "approved", "create_if_missing": True},
            headers=_auth("co-ceo"),
        )
        assert r.status_code == 422

    def test_404_unknown_gate_no_create(self, client):
        r = client.post(
            "/org/gates/nonexistent/decide",
            json={"decision": "approved", "rationale": "ok"},
            headers=_auth("co-ceo"),
        )
        assert r.status_code == 404

    def test_idempotent_same_decision(self, client):
        self._decide(client, decision="approved")
        r2 = self._decide(client, decision="approved")
        assert r2.status_code == 200
        assert r2.get_json()["idempotent_replay"] is True

    def test_409_opposing_decision(self, client):
        self._decide(client, decision="approved")
        r2 = self._decide(client, decision="rejected")
        assert r2.status_code == 409
        body = r2.get_json()
        assert "opposing decision" in body["error"]
        assert body["existing_decision"] == "approved"

    def test_decided_by_reflects_caller(self, client):
        r = self._decide(client)
        assert r.get_json()["decided_by"] == "human-co-ceo"

    def test_create_if_missing_true_creates_gate(self, client):
        r = self._decide(client, gate_id="brand-new", create_if_missing=True)
        assert r.status_code == 200
        assert r.get_json()["gate_id"] == "brand-new"
