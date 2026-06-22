# Acceptance Test Scenarios

**Author:** Ryan (QA)  
**Date:** 2026-06-22  
**Status:** Draft — ready for QA implementation  
**Source specs:** `runbooks/health.md`, `docs/budgets.md`, `docs/team-org-model.md`

---

## Conventions

- Format: Given / When / Then  
- HTTP status codes use standard RFC 9110 values.  
- `{lane}` is one of: `anthropic`, `openai`, `google`.  
- "USD limit" per lane: Anthropic 500, OpenAI 300, Google 400.  
- "80% threshold" per lane: Anthropic 400, OpenAI 240, Google 320 USD.  
- Tests marked **[RISK]** correspond to a prioritised risk item in the Risk Register section at the end of this document.

---

## 1. Health Endpoint — `GET /healthz`

### 1.1 Happy path

**Given** the service is running and has no required external dependencies in scope  
**When** a client sends `GET /healthz`  
**Then**  
- Response status is `200 OK`  
- `Content-Type` header is `application/json`  
- Body is exactly `{"status":"ok"}` (no extra fields, no trailing whitespace)  
- Response time is under 200 ms (P99)

### 1.2 Endpoint is dependency-free

**Given** the service is running  
**And** all downstream services (database, external APIs) are unreachable  
**When** a client sends `GET /healthz`  
**Then**  
- Response status is still `200 OK`  
- Body is still `{"status":"ok"}`  
- The endpoint does NOT attempt any network call to a dependency

### 1.3 Wrong HTTP method

**Given** the service is running  
**When** a client sends `POST /healthz`  
**Then** response status is `405 Method Not Allowed`

### 1.4 Trailing slash variant

**Given** the service is running  
**When** a client sends `GET /healthz/`  
**Then** response status is either `200 OK` (redirected and served) or `301/308` redirect to `/healthz` — it must NOT return `404`

---

## 2. Budget Endpoints

### 2.1 Get current budget — `GET /budgets/{lane}`

#### 2.1.1 Happy path (Anthropic)

**Given** the Anthropic lane exists with limit 500 USD and some recorded spending  
**When** a client sends `GET /budgets/anthropic`  
**Then**  
- Response status is `200 OK`  
- Body contains `"lane": "anthropic"`  
- Body contains `"limit_usd": 500`  
- Body contains `"spent_usd"` as a non-negative number ≤ 500  
- Body contains `"remaining_usd"` equal to `limit_usd − spent_usd`  
- Body contains `"alert_threshold_usd": 400` (80% of 500)

#### 2.1.2 Happy path (OpenAI)

**Given** the OpenAI lane exists with limit 300 USD  
**When** a client sends `GET /budgets/openai`  
**Then**  
- Response status is `200 OK`  
- `"limit_usd": 300`  
- `"alert_threshold_usd": 240`

#### 2.1.3 Happy path (Google)

**Given** the Google lane exists with limit 400 USD  
**When** a client sends `GET /budgets/google`  
**Then**  
- Response status is `200 OK`  
- `"limit_usd": 400`  
- `"alert_threshold_usd": 320`

#### 2.1.4 Unknown lane

**Given** no lane named `xai` is configured  
**When** a client sends `GET /budgets/xai`  
**Then** response status is `404 Not Found`

#### 2.1.5 Lane name case sensitivity

**When** a client sends `GET /budgets/Anthropic` (mixed case)  
**Then** response status is `404 Not Found` or `400 Bad Request` — must NOT silently alias to the `anthropic` lane

### 2.2 Record spending — `POST /budgets/{lane}/usage`

#### 2.2.1 Happy path — spend within remaining budget

**Given** the Anthropic lane has `spent_usd = 100` (remaining: 400)  
**When** a client sends `POST /budgets/anthropic/usage` with body `{"amount_usd": 50}`  
**Then**  
- Response status is `200 OK`  
- `spent_usd` is now `150`  
- `remaining_usd` is now `350`  
- `"alert_triggered": false`

#### 2.2.2 Spend crosses 80% alert threshold **[RISK R-1]**

**Given** the OpenAI lane has `spent_usd = 230` (remaining: 70)  
**When** a client sends `POST /budgets/openai/usage` with body `{"amount_usd": 20}`  
**Then**  
- Response status is `200 OK`  
- `spent_usd` is now `250` (> 240 threshold)  
- Body or response header indicates `"alert_triggered": true`  
- An alert notification is emitted (log entry, webhook, or event — mechanism is implementation-defined but must be verifiable)

#### 2.2.3 Spend would exactly reach the limit — must be blocked **[RISK R-1]**

**Given** the Google lane has `spent_usd = 395` (remaining: 5)  
**When** a client sends `POST /budgets/google/usage` with body `{"amount_usd": 5}`  
**Then**  
- Response status is `402 Payment Required` or `429 Too Many Requests`  
- `spent_usd` remains `395` — the amount is NOT applied  
- Body contains a machine-readable error code such as `"error": "budget_limit_reached"`

> **Rationale:** `docs/budgets.md` states "never auto-exceeds". Spending that would bring `spent_usd` to exactly the limit still exhausts the budget, so it must be treated the same as an over-limit request.

#### 2.2.4 Spend would exceed the limit — must be blocked **[RISK R-1]**

**Given** the Google lane has `spent_usd = 390` (remaining: 10)  
**When** a client sends `POST /budgets/google/usage` with body `{"amount_usd": 50}`  
**Then**  
- Response status is `402` or `429`  
- `spent_usd` remains `390`  
- Body contains `"error": "budget_limit_reached"` (or equivalent)

#### 2.2.5 Zero-amount request

**When** a client sends `POST /budgets/anthropic/usage` with body `{"amount_usd": 0}`  
**Then** response status is `400 Bad Request` — a zero spend has no business meaning and likely indicates a client bug

#### 2.2.6 Negative amount

**When** a client sends `POST /budgets/anthropic/usage` with body `{"amount_usd": -10}`  
**Then** response status is `400 Bad Request`

#### 2.2.7 Missing required field

**When** a client sends `POST /budgets/anthropic/usage` with body `{}`  
**Then** response status is `400 Bad Request`

#### 2.2.8 Non-numeric amount

**When** a client sends `POST /budgets/anthropic/usage` with body `{"amount_usd": "fifty"}`  
**Then** response status is `400 Bad Request`

#### 2.2.9 Extremely large amount (integer overflow boundary)

**When** a client sends `POST /budgets/anthropic/usage` with body `{"amount_usd": 9007199254740993}` (> MAX_SAFE_INTEGER)  
**Then** response status is `400 Bad Request`

#### 2.2.10 Unknown lane

**When** a client sends `POST /budgets/xai/usage` with body `{"amount_usd": 10}`  
**Then** response status is `404 Not Found`

### 2.3 Query whether spending is permitted — `GET /budgets/{lane}/can-spend?amount={n}`

#### 2.3.1 Amount is within remaining budget

**Given** OpenAI lane has `spent_usd = 100` (remaining: 200)  
**When** a client sends `GET /budgets/openai/can-spend?amount=50`  
**Then**  
- Response status is `200 OK`  
- Body contains `"permitted": true`

#### 2.3.2 Amount would exceed limit

**Given** OpenAI lane has `spent_usd = 280` (remaining: 20)  
**When** a client sends `GET /budgets/openai/can-spend?amount=50`  
**Then**  
- Response status is `200 OK`  
- Body contains `"permitted": false`  
- Body contains an explanatory field such as `"reason": "insufficient_budget"`

#### 2.3.3 Amount equals remaining exactly

**Given** Google lane has `spent_usd = 350` (remaining: 50)  
**When** a client sends `GET /budgets/google/can-spend?amount=50`  
**Then**  
- `"permitted": false` — spending the last dollar would exhaust the budget; consistent with "never auto-exceeds"

#### 2.3.4 Missing query parameter

**When** a client sends `GET /budgets/anthropic/can-spend` (no `amount`)  
**Then** response status is `400 Bad Request`

#### 2.3.5 Non-numeric query parameter

**When** a client sends `GET /budgets/anthropic/can-spend?amount=abc`  
**Then** response status is `400 Bad Request`

---

## 3. Org / Team Endpoints

### 3.1 Get org structure — `GET /org`

#### 3.1.1 Happy path

**Given** the Nexocloud org is configured  
**When** a client sends `GET /org`  
**Then**  
- Response status is `200 OK`  
- Body contains a `"ceo"` field with `"name": "Atlas"` and `"type": "ai"`  
- Body contains a `"co_ceo"` (or equivalent) with `"type": "human"` and gate level `"L4"`  
- Body contains the C-suite and their divisions (exact schema is implementation-defined but must be present)

#### 3.1.2 Structural integrity — Atlas is AI CEO

**Given** the org is returned  
**When** the client inspects the CEO record  
**Then**  
- `"name"` is `"Atlas"`  
- `"role"` or `"type"` indicates AI, not human

#### 3.1.3 L4 gate held by human co-CEO

**Given** the org is returned  
**Then**  
- Exactly one entity has `"gate_level": "L4"` (or equivalent field)  
- That entity's `"type"` is `"human"`  
- No AI entity has `"gate_level": "L4"`

### 3.2 Get a specific member — `GET /org/members/{id}`

#### 3.2.1 Happy path — Atlas

**Given** Atlas exists with a known ID  
**When** a client sends `GET /org/members/{atlas_id}`  
**Then**  
- Response status is `200 OK`  
- Body contains `"name": "Atlas"`, `"role": "ai_ceo"` (or equivalent)

#### 3.2.2 Unknown member ID

**When** a client sends `GET /org/members/9999`  
**Then** response status is `404 Not Found`

#### 3.2.3 Non-integer ID

**When** a client sends `GET /org/members/abc`  
**Then** response status is `400 Bad Request` or `404 Not Found`

### 3.3 List tasks delegated by Atlas — `GET /org/tasks`

#### 3.3.1 Happy path — tasks present

**Given** Atlas has decomposed a project and delegated tasks  
**When** a client sends `GET /org/tasks`  
**Then**  
- Response status is `200 OK`  
- Body is a JSON array  
- Each item contains at minimum: `"id"`, `"title"`, `"delegated_to"`, `"status"`

#### 3.3.2 No tasks yet

**Given** no tasks have been delegated  
**When** a client sends `GET /org/tasks`  
**Then**  
- Response status is `200 OK`  
- Body is an empty array `[]`  
- Must NOT return `404`

#### 3.3.3 Filtering by assignee

**When** a client sends `GET /org/tasks?assignee={member_id}`  
**Then** only tasks delegated to that member are returned

### 3.4 Create a task — `POST /org/tasks`

#### 3.4.1 Happy path

**Given** a valid task payload  
**When** a client sends `POST /org/tasks` with body:
```json
{"title": "Design auth module", "delegated_to": 2, "due_date": "2026-07-01"}
```
**Then**  
- Response status is `201 Created`  
- Body contains the created task with a server-generated `"id"`  
- `Location` header points to `GET /org/tasks/{id}`

#### 3.4.2 Missing required field `title`

**When** a client sends `POST /org/tasks` with body `{"delegated_to": 2}`  
**Then** response status is `400 Bad Request`

#### 3.4.3 Unknown `delegated_to` member

**When** `delegated_to` references a non-existent member ID  
**Then** response status is `422 Unprocessable Entity`

#### 3.4.4 Duplicate task title (if unique constraint exists)

**Given** a task titled "Design auth module" already exists  
**When** the same title is submitted again  
**Then** response status is `409 Conflict`  
**(Skip this scenario if uniqueness is not a business requirement.)**

### 3.5 Update a task — `PUT /org/tasks/{id}` **[RISK R-4]**

#### 3.5.1 Happy path

**Given** task with `id = 7` exists  
**When** a client sends `PUT /org/tasks/7` with body `{"status": "done"}`  
**Then**  
- Response status is `200 OK`  
- `"status"` in the response is `"done"`  
- `"id"` in the response is still `7`

#### 3.5.2 Caller-supplied `id` field in body must be ignored **[RISK R-4]**

**Given** task with `id = 7` exists  
**When** a client sends `PUT /org/tasks/7` with body `{"id": 999, "status": "done"}`  
**Then**  
- Response status is `200 OK`  
- The task's `id` remains `7` — it must NOT be overwritten to `999`  
- `GET /org/tasks/7` still returns the task  
- `GET /org/tasks/999` returns `404`

#### 3.5.3 Task not found

**When** a client sends `PUT /org/tasks/9999` with a valid body  
**Then** response status is `404 Not Found`

#### 3.5.4 Invalid status value

**When** `"status"` is set to an undefined value (e.g. `"flying"`)  
**Then** response status is `400 Bad Request`

### 3.6 L4 gate — escalation to human co-CEO

#### 3.6.1 L4-gated action is blocked for AI initiator

**Given** a task or decision is classified as requiring an L4 gate  
**When** Atlas attempts to approve it directly via API  
**Then**  
- The action is rejected (status `403 Forbidden`)  
- Body contains `"error": "l4_gate_required"` or equivalent  
- An escalation record is created for the human co-CEO

#### 3.6.2 L4-gated action succeeds for human co-CEO

**Given** the same L4-gated action  
**When** the human co-CEO submits approval  
**Then**  
- Response status is `200 OK`  
- Action is applied

---

## 4. Chat / AI Proxy Endpoint — `POST /chat` **[RISK R-2]**

### 4.1 Happy path — within budget

**Given** the target lane (e.g. Anthropic) has sufficient remaining budget  
**When** a client sends `POST /chat` with body `{"lane": "anthropic", "message": "Hello"}`  
**Then**  
- Response status is `200 OK`  
- Body contains `"reply"` with the AI-generated response  
- Usage for this call is recorded against the Anthropic budget **[RISK R-2]**

### 4.2 Budget exhausted — request blocked

**Given** the Anthropic lane has `spent_usd = 500` (0 remaining)  
**When** a client sends `POST /chat` with body `{"lane": "anthropic", "message": "Hello"}`  
**Then**  
- Response status is `402 Payment Required` or `429`  
- No call is made to the Anthropic API  
- Body contains `"error": "budget_limit_reached"`

### 4.3 Budget check and spend are atomic **[RISK R-2]**

**Given** concurrent requests that would each fit individually but together would exceed the budget  
**When** both requests arrive simultaneously  
**Then** exactly one succeeds and exactly one is rejected — the budget is never exceeded by race condition

### 4.4 Missing `lane` field

**When** a client sends `POST /chat` with body `{"message": "Hello"}` (no `lane`)  
**Then** response status is `400 Bad Request`

### 4.5 Unknown lane

**When** `"lane": "xai"` is specified  
**Then** response status is `400 Bad Request` or `422`

### 4.6 Empty message

**When** `"message": ""` is submitted  
**Then** response status is `400 Bad Request`

### 4.7 Upstream AI API error

**Given** the target lane's API returns a 5xx error  
**When** the request is forwarded  
**Then**  
- Response status is `502 Bad Gateway`  
- If spend was pre-decremented, it must be rolled back **[RISK R-2]**

---

## 5. Admin Endpoints — `GET /admin/budgets`, `PUT /admin/budgets/{lane}` **[RISK R-3]**

### 5.1 Read all budget limits (authenticated)

**Given** a valid admin credential is presented  
**When** a client sends `GET /admin/budgets` with the credential  
**Then**  
- Response status is `200 OK`  
- Body lists all three lanes with their limits and current spend

### 5.2 Read all budget limits — unauthenticated **[RISK R-3]**

**When** a client sends `GET /admin/budgets` with no credential  
**Then** response status is `401 Unauthorized`

### 5.3 Update a lane limit (authenticated)

**Given** a valid admin credential  
**When** a client sends `PUT /admin/budgets/anthropic` with body `{"limit_usd": 600}`  
**Then**  
- Response status is `200 OK`  
- `GET /budgets/anthropic` subsequently returns `"limit_usd": 600`

### 5.4 Update a lane limit — unauthenticated **[RISK R-3]**

**When** a client sends `PUT /admin/budgets/anthropic` with no credential  
**Then** response status is `401 Unauthorized` and the limit is NOT changed

### 5.5 Update a lane limit — insufficient privilege **[RISK R-3]**

**Given** a non-admin authenticated token  
**When** a client sends `PUT /admin/budgets/anthropic` with body `{"limit_usd": 0}`  
**Then** response status is `403 Forbidden`

### 5.6 Setting limit below current spend

**Given** the Anthropic lane has `spent_usd = 300`  
**When** an admin sets `limit_usd` to `200`  
**Then**  
- Response status is `422 Unprocessable Entity` or `400 Bad Request`  
- Limit is NOT changed, to avoid silent overspend

### 5.7 Setting limit to zero or negative

**When** an admin sends `{"limit_usd": 0}` or `{"limit_usd": -1}`  
**Then** response status is `400 Bad Request`

---

## Risk Register

Findings discovered during scenario derivation that require engineering attention before QA can close these scenarios.

| ID | Severity | Endpoint | Finding | Spec reference |
|----|----------|----------|---------|----------------|
| R-1 | **High** | `POST /budgets/{lane}/usage` | No cap enforcement: `record_usage` can push `spent` past the budget limit, violating "never auto-exceeds". | `docs/budgets.md` |
| R-2 | **High** | `POST /chat` | Budget check (`can_spend`) and spend recording (`record_usage`) appear decoupled — a race or a missing call means actual API spend is never reliably decremented. | `docs/budgets.md` |
| R-3 | **High** | `GET /admin/budgets`, `PUT /admin/budgets/{lane}` | No authentication gate specified in any runbook; unauthenticated mutation of budget limits is possible. | `docs/budgets.md`, `docs/team-org-model.md` |
| R-4 | **Medium** | `PUT /org/tasks/{id}` | A caller-supplied `"id"` field in the request body may be applied via a dict merge, overwriting the task's primary key and making it unreachable. | `docs/team-org-model.md` |
| R-5 | **Medium** | `GET /healthz` | No spec for behaviour under partial degradation (e.g. DB read-only). Confirm the endpoint truly has zero dependencies before closing 1.2. | `runbooks/health.md` |
| R-6 | **Low** | All budget endpoints | Alert at 80% is specified but delivery mechanism (webhook, email, log) is unspecified. Scenario 2.2.2 cannot be fully automated until this is defined. | `docs/budgets.md` |
| R-7 | **Low** | `POST /org/tasks` | `due_date` format not specified — ISO 8601 (`YYYY-MM-DD`) should be enforced to prevent locale-dependent parsing bugs. | `docs/team-org-model.md` |