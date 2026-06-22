# Nexocloud API Test Plan

**Version:** 1.0  **Date:** 2026-06-22  **Owner:** Engineering / QA

---

## 1. Scope

All endpoints defined in `openapi.yaml`:

| # | Method | Path | operationId |
|---|--------|------|-------------|
| 1 | GET | `/healthz` | `getHealth` |
| 2 | POST | `/projects` | `createProject` |
| 3 | GET | `/projects` | `listProjects` |
| 4 | GET | `/projects/{projectId}` | `getProject` |
| 5 | DELETE | `/projects/{projectId}` | `deleteProject` |
| 6 | POST | `/projects/{projectId}/tasks` | `delegateTask` |
| 7 | GET | `/budget/status` | `getBudgetStatus` |
| 8 | POST | `/approvals/{gateId}` | `submitApproval` |

---

## 2. Test Layers

### Unit tests

Handler logic in isolation; all I/O dependencies stubbed.

| Endpoint | Scenarios |
|----------|-----------|
| `getHealth` | 200 `{"status":"ok"}`; no downstream calls |
| `createProject` | 201 on valid body; 400 on missing `name`; 422 on invalid field type |
| `listProjects` | 200 with empty list; 200 with populated list |
| `getProject` | 200 on known ID; 404 on unknown ID |
| `deleteProject` | 204 on known ID; 404 on unknown ID |
| `delegateTask` | 202 on valid body; 400 on missing `description`/`agent`; 404 on unknown `projectId` |
| `getBudgetStatus` | 200 with lanes array; each lane has `provider`, `budget_usd`, `consumed_usd`, `alert_threshold_pct` |
| `submitApproval` | 200 approve; 200 reject; 400 invalid `decision` value; 404 unknown gate; 409 already-decided gate |

### Integration tests

Real server, ephemeral test database; external AI providers stubbed.

| Scenario | Expected result |
|----------|-----------------|
| `createProject` then `listProjects` | Created project appears in list |
| `createProject` then `getProject` | Response matches posted body |
| `createProject` then `deleteProject` then `getProject` | 404 after deletion |
| `createProject` then `delegateTask` | 202; task persisted against project |
| `delegateTask` on deleted project | 404 |
| `getBudgetStatus` | Lanes for Anthropic ($500), OpenAI ($300), Google ($400); `alert_threshold_pct` is 80 |
| `submitApproval` approve then approve again | Second call returns 409 |
| `submitApproval` on unknown gate | 404 |

### Contract tests

Every response from the running server validated against `openapi.yaml`; run after integration tests pass.

| Verification | Detail |
|--------------|--------|
| Status codes | Every response code matches a declared response for that operation |
| Response schemas | Every response body validates against the declared JSON schema |
| Request validation | Invalid `decision` enum value rejected with 400 |
| Path coverage | 100% of paths x methods in `openapi.yaml` exercised |

---

## 3. Tools and Frameworks

| Layer | Tool | Notes |
|-------|------|-------|
| Unit | Jest/Vitest (TypeScript) or pytest (Python) | Match the implementation language |
| Integration | Supertest (Node) or HTTPX + pytest (Python) | Real server, ephemeral database per run |
| Contract | Schemathesis against `openapi.yaml` | `--stateful=links` for chained flows |
| Coverage | Istanbul/nyc (TS) or Coverage.py (Python) | Enforced in CI; report published as artifact |
| CI | GitHub Actions | All layers run on every pull request |

---

## 4. Coverage Thresholds

| Metric | Threshold | Enforced by |
|--------|-----------|-------------|
| Line (unit) | >= 80% | CI coverage gate |
| Branch (unit) | >= 75% | CI coverage gate |
| Endpoint (contract) | 100% of paths x methods in `openapi.yaml` | Schemathesis `--validate-schema=true` |
| Integration happy-path | 100% of endpoints have at least one passing integration test | Zero skips allowed |

Build fails if any threshold is not met.

---

## 5. Entry Criteria

- `openapi.yaml` passes `swagger-parser` lint with zero errors.
- A runnable build artifact (Docker image or local server) is available.
- Test database and fixtures are seeded and isolated per test run.
- All unit tests from the previous passing build remain green.

## 6. Exit Criteria

- All unit, integration, and contract tests pass with zero failures.
- Coverage thresholds in section 4 are met.
- No P0 or P1 defects are open against in-scope endpoints.
- Contract test HTML report is attached to the pull request as a CI artifact.

---

## 7. Budget Guardrails

CI must never call live AI provider APIs. Stub or record/replay all Anthropic, OpenAI, and Google calls. This prevents spending against the monthly caps (Anthropic $500, OpenAI $300, Google $400) and ensures the 80% alert threshold logic is tested against deterministic fixture data rather than live consumption.

---

## 8. L4 Gate Handling

`POST /approvals/{gateId}` drives the human Co-CEO approval flow. In all test environments:

- Seed synthetic gate IDs in fixtures before each test run.
- Never invoke the production approval service from CI.
- The 409 (already-decided) case must be an explicit integration test, not an optional edge case.