# API Business Logic

This document is the authoritative reference for every endpoint's authorisation
requirements, idempotency semantics, rate-limiting behaviour, side effects, and
error contracts.  Keep it in sync with `app.py`; the inline docstrings are the
machine-readable equivalent of this document.

---

## Common conventions

| Convention | Detail |
|---|---|
| Authentication | All protected endpoints require `Authorization: Bearer <token>`. Missing or unrecognised tokens return `401`. |
| Authorisation | Role-based; wrong role returns `403`. |
| Rate limiting | Per-token, per-endpoint sliding window. Exceeding the limit returns `429`. |
| Content-Type | Request bodies must be `application/json`; malformed JSON is treated as an empty object. |
| Idempotency | Where noted, callers supply a `request_id`; the server replays the original response without re-applying side effects. |

---

## Endpoints

### `GET /healthz`

**Purpose** — liveness probe; used by infrastructure health checks.

| Dimension | Behaviour |
|---|---|
| Auth | None. |
| Rate limiting | None — health checks must remain reachable even under load. |
| Idempotency | Unconditionally idempotent; no state is read or written. |
| Side effects | None. |
| Invalid input | No input accepted; all query parameters and bodies are ignored. |
| Missing resources | N/A. |

#### Responses

| Code | Body | When |
|---|---|---|
| `200` | `{"status": "ok"}` | Always. |

The response is kept dependency-free (see `runbooks/health.md`); it does **not**
reflect downstream service health.

---

### `GET /budgets`

**Purpose** — return the monthly cap and running spend for every API lane.

Monthly caps per `docs/budgets.md`: Anthropic $500, OpenAI $300, Google $400.

| Dimension | Behaviour |
|---|---|
| Auth | Bearer token required; any valid role is accepted. Missing/invalid → `401`. |
| Rate limiting | 100 req / token / 60 s → `429`. |
| Idempotency | Unconditionally idempotent (read-only). |
| Side effects | None. |
| Invalid input | Query parameters ignored; no request body. |
| Missing resources | N/A — lane list is static. |

#### Responses

| Code | Body | When |
|---|---|---|
| `200` | `{"lanes": [{lane object}, …]}` | Always when authenticated. |
| `401` | `{"error": "…"}` | Token missing or invalid. |
| `429` | `{"error": "rate limit exceeded"}` | Token exceeds 100 req/60 s. |

**Lane object fields**

```json
{
  "lane": "anthropic",
  "cap_usd": 500,
  "spend_usd": 123.45,
  "alert_threshold": 0.8,
  "alert_fired": false
}
```

---

### `GET /budgets/<lane>`

**Purpose** — return the monthly cap and running spend for a single lane.

| Dimension | Behaviour |
|---|---|
| Auth | Bearer token required; any valid role is accepted → `401`. |
| Rate limiting | 100 req / token / 60 s → `429`. |
| Idempotency | Unconditionally idempotent (read-only). |
| Side effects | None. |
| Invalid input | `<lane>` must be one of `{anthropic, openai, google}` → `404`. |
| Missing resources | Unknown lane → `404`. |

#### Responses

| Code | Body | When |
|---|---|---|
| `200` | Lane object (same schema as above) | Lane found. |
| `401` | `{"error": "…"}` | Token missing or invalid. |
| `404` | `{"error": "lane not found"}` | `<lane>` not in known set. |
| `429` | `{"error": "rate limit exceeded"}` | Token exceeds 100 req/60 s. |

---

### `POST /budgets/<lane>/spend`

**Purpose** — record API spend against a lane (called by internal services after
each chargeable API call).

From `docs/budgets.md`: Paperclip **alerts at 80 %** and **never auto-exceeds**
the monthly cap.

| Dimension | Behaviour |
|---|---|
| Auth | Bearer token with role `service` required. Missing/invalid → `401`. Wrong role → `403`. |
| Rate limiting | 300 req / token / 60 s → `429`. |
| Idempotency | Callers **must** supply a unique `request_id` per spend event. Duplicate `request_id` for the same lane replays the original response without re-applying the spend. |
| Side effects | (1) Increments running spend for the lane. (2) Fires a `budget.alert` event (reflected in `alert_fired: true`) the **first** time spend crosses 80 % of cap in the current period. (3) **Rejects** requests that would push spend past the cap (`402`) — spend total is **not** mutated. |
| Invalid input | Missing/non-positive `amount` → `422`. Missing `request_id` → `422`. Unknown `lane` → `404`. |
| Missing resources | Unknown lane → `404`. |

#### Request body

```json
{ "amount": 12.50, "request_id": "uuid-or-similar" }
```

#### Responses

| Code | Body | When |
|---|---|---|
| `200` | Spend record (see below) | Spend accepted or idempotent replay. |
| `402` | `{"error": "budget cap exceeded", "cap_usd": …, "spend_usd": …, "requested": …}` | Amount would exceed cap. |
| `401` | `{"error": "…"}` | Token missing or invalid. |
| `403` | `{"error": "role 'service' required"}` | Non-service token. |
| `404` | `{"error": "lane not found"}` | Unknown lane. |
| `422` | `{"error": "…"}` | Missing/invalid `amount` or `request_id`. |
| `429` | `{"error": "rate limit exceeded"}` | Token exceeds 300 req/60 s. |

**Spend record fields**

```json
{
  "lane": "anthropic",
  "recorded": 12.50,
  "total_spend": 135.95,
  "cap_usd": 500,
  "alert_fired": false,
  "idempotent_replay": false
}
```

`alert_fired` is `true` only for the single request that first crosses 80 %.
Subsequent requests return `false` even if spend remains above the threshold.
`idempotent_replay` is `true` when the `request_id` was already processed.

---

### `POST /org/gates/<gate_id>/decide`

**Purpose** — the human Co-CEO records an L4 gate decision (approve or reject).
Per `docs/team-org-model.md`, the human Co-CEO holds all L4 gates; AI CEO Atlas
decomposes projects but cannot decide gates.

| Dimension | Behaviour |
|---|---|
| Auth | Bearer token with role `co-ceo` required. Missing/invalid → `401`. Wrong role → `403`. |
| Rate limiting | 10 req / token / 60 s → `429`. (Low limit — gate decisions are deliberate human acts.) |
| Idempotency | Repeated call with the **same** `gate_id` **and** the **same** `decision` → `200` with original record and `idempotent_replay: true`. Repeated call with the **opposite** decision → `409` (decided gates cannot be reversed via this endpoint; use the override workflow). |
| Side effects | (1) Creates a gate decision record. (2) Emits `gate.decided` event (reflected in response). (3) On `approved`: triggers Atlas delegation flow. (4) On `rejected`: queues rejection notification to requester. |
| Invalid input | `decision` not in `{approved, rejected}` → `422`. Missing `rationale` → `422`. |
| Missing resources | Unknown `gate_id` and `create_if_missing` is `false` (default) → `404`. Set `create_if_missing: true` to open and immediately decide a new gate. |

#### Request body

```json
{
  "decision": "approved",
  "rationale": "Risk assessment complete; proceed.",
  "create_if_missing": false
}
```

#### Responses

| Code | Body | When |
|---|---|---|
| `200` | Gate record (see below) | Decision recorded or idempotent replay. |
| `401` | `{"error": "…"}` | Token missing or invalid. |
| `403` | `{"error": "role 'co-ceo' required"}` | Non-co-ceo token. |
| `404` | `{"error": "gate not found"}` | Unknown `gate_id` and `create_if_missing` is `false`. |
| `409` | `{"error": "gate already decided with opposing decision", "existing_decision": "…"}` | Conflict on flip. |
| `422` | `{"error": "…"}` | Invalid `decision` or missing `rationale`. |
| `429` | `{"error": "rate limit exceeded"}` | Token exceeds 10 req/60 s. |

**Gate record fields**

```json
{
  "gate_id": "proj-42-l4",
  "decision": "approved",
  "rationale": "Risk assessment complete; proceed.",
  "decided_at": 1719000000.0,
  "decided_by": "human-co-ceo",
  "event": "gate.decided",
  "idempotent_replay": false
}
```