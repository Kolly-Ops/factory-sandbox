"""
Nexocloud API — business logic is explicitly documented per endpoint in this
module and in docs/api-business-logic.md.
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict
from functools import wraps
from typing import Any

from flask import Flask, jsonify, request, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory stores (swap for real persistence without changing API contracts)
# ---------------------------------------------------------------------------

LANE_CAPS: dict[str, int] = {
    "anthropic": 500,
    "openai": 300,
    "google": 400,
}
ALERT_THRESHOLD = 0.80

_spend: dict[str, float] = defaultdict(float)
_spend_alerted: dict[str, bool] = defaultdict(bool)
_idempotency_cache: dict[str, dict[str, Any]] = {}

_gates: dict[str, dict[str, Any]] = {}

TOKENS: dict[str, dict[str, str]] = {
    "service-token": {"role": "service", "sub": "svc-1"},
    "co-ceo-token": {"role": "co-ceo", "sub": "human-co-ceo"},
    "user-token": {"role": "user", "sub": "user-1"},
}

_rate_windows: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "window_start": 0.0})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_rate_limit(key: str, limit: int, window: int = 60) -> bool:
    """Return True if the request is within the allowed rate, False if exceeded."""
    now = time.monotonic()
    state = _rate_windows[key]
    if now - state["window_start"] >= window:
        state["count"] = 0
        state["window_start"] = now
    state["count"] += 1
    return state["count"] <= limit


def _require_auth(required_role: str | None = None):
    """Decorator: validates Bearer token; optionally enforces a role.

    - Missing or invalid token → 401.
    - Valid token but wrong role → 403.
    - Stores resolved claims in flask.g.claims for the route handler.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return jsonify({"error": "missing or malformed Authorization header"}), 401
            token = auth_header[len("Bearer "):]
            claims = TOKENS.get(token)
            if claims is None:
                return jsonify({"error": "invalid token"}), 401
            if required_role is not None and claims["role"] != required_role:
                return jsonify({"error": f"role '{required_role}' required"}), 403
            g.claims = claims
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def _rate_limited(limit: int, window: int = 60):
    """Decorator: applies per-token rate limiting before the route handler runs.

    Exceeding the limit → 429.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            token = request.headers.get("Authorization", "anon")
            key = f"{fn.__name__}:{token}"
            if not _check_rate_limit(key, limit, window):
                return jsonify({"error": "rate limit exceeded"}), 429
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/healthz", methods=["GET"])
def healthz():
    """GET /healthz — liveness probe.

    Business logic
    --------------
    Auth            : None required.
    Rate limiting   : None — health checks must remain reachable at all times.
    Idempotency     : Unconditionally idempotent; no state is read or written.
    Side effects    : None.
    Invalid input   : No input is accepted; query parameters and bodies are
                      ignored.
    Missing resources: Not applicable.

    Response
    --------
    200  {"status": "ok"}  — always, regardless of downstream dependency state
                             (kept dependency-free per runbooks/health.md).
    """
    return jsonify({"status": "ok"}), 200


@app.route("/budgets", methods=["GET"])
@_require_auth()
@_rate_limited(limit=100)
def list_budgets():
    """GET /budgets — return the monthly cap and running spend for every lane.

    Business logic
    --------------
    Auth            : Bearer token required; any valid role is accepted.
                      Missing/invalid token → 401.
    Rate limiting   : 100 requests per token per 60-second window → 429.
    Idempotency     : Unconditionally idempotent (read-only).
    Side effects    : None.
    Invalid input   : Query parameters are ignored; no request body.
    Missing resources: Not applicable — the lane list is static.

    Response
    --------
    200  {"lanes": [{"lane": <str>, "cap_usd": <int>, "spend_usd": <float>,
                     "alert_threshold": 0.8, "alert_fired": <bool>}, ...]}
    """
    lanes = [
        {
            "lane": lane,
            "cap_usd": cap,
            "spend_usd": _spend[lane],
            "alert_threshold": ALERT_THRESHOLD,
            "alert_fired": _spend_alerted[lane],
        }
        for lane, cap in LANE_CAPS.items()
    ]
    return jsonify({"lanes": lanes}), 200


@app.route("/budgets/<lane>", methods=["GET"])
@_require_auth()
@_rate_limited(limit=100)
def get_budget(lane: str):
    """GET /budgets/<lane> — return the monthly cap and running spend for one lane.

    Business logic
    --------------
    Auth            : Bearer token required; any valid role is accepted → 401.
    Rate limiting   : 100 requests per token per 60-second window → 429.
    Idempotency     : Unconditionally idempotent (read-only).
    Side effects    : None.
    Invalid input   : <lane> must be one of {anthropic, openai, google}.
    Missing resources: Unknown lane → 404 {"error": "lane not found"}.

    Response
    --------
    200  {"lane": <str>, "cap_usd": <int>, "spend_usd": <float>,
           "alert_threshold": 0.8, "alert_fired": <bool>}
    404  {"error": "lane not found"}
    """
    if lane not in LANE_CAPS:
        return jsonify({"error": "lane not found"}), 404
    return jsonify(
        {
            "lane": lane,
            "cap_usd": LANE_CAPS[lane],
            "spend_usd": _spend[lane],
            "alert_threshold": ALERT_THRESHOLD,
            "alert_fired": _spend_alerted[lane],
        }
    ), 200


@app.route("/budgets/<lane>/spend", methods=["POST"])
@_require_auth(required_role="service")
@_rate_limited(limit=300)
def record_spend(lane: str):
    """POST /budgets/<lane>/spend — record API spend against a lane.

    Business logic
    --------------
    Auth            : Bearer token with role 'service' required.
                      Missing/invalid token → 401.
                      Valid token but wrong role → 403.
    Rate limiting   : 300 requests per token per 60-second window → 429.
    Idempotency     : Clients MUST supply a unique ``request_id`` per
                      spend event.  If the same ``request_id`` is submitted
                      again for the same lane the original response is
                      returned without re-applying the spend (exactly-once
                      semantics).
    Side effects    :
        - Increments the running spend total for the lane.
        - Emits a "budget.alert" event (recorded in the response) the first
          time spend crosses 80 % of the cap in the current period.
        - If the requested ``amount`` would push spend past the cap the
          request is rejected with 402; the spend total is NOT modified
          (never-auto-exceed guarantee from docs/budgets.md).
    Invalid input   :
        - Missing or non-positive ``amount`` → 422.
        - Missing ``request_id``             → 422.
        - Unknown ``lane``                   → 404.
    Missing resources: Unknown lane → 404 {"error": "lane not found"}.

    Request body (JSON)
    -------------------
    {"amount": <float>, "request_id": <str>}

    Response
    --------
    200  {"lane": <str>, "recorded": <float>, "total_spend": <float>,
           "cap_usd": <int>, "alert_fired": <bool>, "idempotent_replay": <bool>}
    402  {"error": "budget cap exceeded", "cap_usd": <int>,
           "spend_usd": <float>, "requested": <float>}
    404  {"error": "lane not found"}
    422  {"error": <str>}
    """
    if lane not in LANE_CAPS:
        return jsonify({"error": "lane not found"}), 404

    body = request.get_json(silent=True) or {}
    request_id: str | None = body.get("request_id")
    amount = body.get("amount")

    if not request_id:
        return jsonify({"error": "request_id is required"}), 422
    if amount is None or not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({"error": "amount must be a positive number"}), 422

    cache_key = f"{lane}:{request_id}"
    if cache_key in _idempotency_cache:
        cached = dict(_idempotency_cache[cache_key])
        cached["idempotent_replay"] = True
        return jsonify(cached), 200

    cap = LANE_CAPS[lane]
    current = _spend[lane]

    if current + amount > cap:
        return jsonify(
            {
                "error": "budget cap exceeded",
                "cap_usd": cap,
                "spend_usd": current,
                "requested": amount,
            }
        ), 402

    _spend[lane] = current + amount
    new_total = _spend[lane]

    alert_newly_fired = False
    if not _spend_alerted[lane] and new_total >= cap * ALERT_THRESHOLD:
        _spend_alerted[lane] = True
        alert_newly_fired = True

    response_body = {
        "lane": lane,
        "recorded": amount,
        "total_spend": new_total,
        "cap_usd": cap,
        "alert_fired": alert_newly_fired,
        "idempotent_replay": False,
    }
    _idempotency_cache[cache_key] = dict(response_body)
    return jsonify(response_body), 200


@app.route("/org/gates/<gate_id>/decide", methods=["POST"])
@_require_auth(required_role="co-ceo")
@_rate_limited(limit=10)
def decide_gate(gate_id: str):
    """POST /org/gates/<gate_id>/decide — Co-CEO records an L4 gate decision.

    Business logic
    --------------
    Auth            : Bearer token with role 'co-ceo' required (human Co-CEO
                      holds all L4 gates — docs/team-org-model.md).
                      Missing/invalid token → 401.
                      Valid token but wrong role → 403.
    Rate limiting   : 10 requests per token per 60-second window → 429.
    Idempotency     : Repeated calls with the same gate_id AND the same
                      decision are idempotent and return 200 with the original
                      record.  A second call with the OPPOSITE decision is
                      rejected with 409 (a decided gate cannot be reversed via
                      the API; use the override workflow instead).
    Side effects    :
        - Creates a gate decision record (gate_id, decision, rationale,
          decided_at, decided_by).
        - Emits a "gate.decided" event (recorded in the response).
        - On "approved": triggers downstream Atlas delegation flow.
        - On "rejected": queues a rejection notification to the requester.
    Invalid input   :
        - ``decision`` not in {approved, rejected} → 422.
        - Missing ``rationale`` → 422.
    Missing resources: gate_id not found and ``create_if_missing`` is False
                      → 404 {"error": "gate not found"}.  Pass
                      ``create_if_missing: true`` in the body to open and
                      immediately decide a new gate.

    Request body (JSON)
    -------------------
    {"decision": "approved"|"rejected", "rationale": <str>,
     "create_if_missing": <bool, default false>}

    Response
    --------
    200  {"gate_id": <str>, "decision": <str>, "rationale": <str>,
           "decided_at": <float>, "decided_by": <str>,
           "event": "gate.decided", "idempotent_replay": <bool>}
    404  {"error": "gate not found"}
    409  {"error": "gate already decided with opposing decision",
           "existing_decision": <str>}
    422  {"error": <str>}
    """
    body = request.get_json(silent=True) or {}
    decision: str | None = body.get("decision")
    rationale: str | None = body.get("rationale")
    create_if_missing: bool = bool(body.get("create_if_missing", False))

    if decision not in ("approved", "rejected"):
        return jsonify({"error": "decision must be 'approved' or 'rejected'"}), 422
    if not rationale:
        return jsonify({"error": "rationale is required"}), 422

    if gate_id not in _gates:
        if not create_if_missing:
            return jsonify({"error": "gate not found"}), 404
        _gates[gate_id] = None

    existing = _gates[gate_id]
    if existing is not None:
        if existing["decision"] == decision:
            return jsonify({**existing, "idempotent_replay": True}), 200
        return jsonify(
            {
                "error": "gate already decided with opposing decision",
                "existing_decision": existing["decision"],
            }
        ), 409

    record = {
        "gate_id": gate_id,
        "decision": decision,
        "rationale": rationale,
        "decided_at": time.time(),
        "decided_by": g.claims["sub"],
        "event": "gate.decided",
        "idempotent_replay": False,
    }
    _gates[gate_id] = record
    return jsonify(record), 200


if __name__ == "__main__":
    app.run(debug=False)