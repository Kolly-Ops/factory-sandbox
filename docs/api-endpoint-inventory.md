# API Endpoint Inventory

**Source of truth for all subsequent specification work.**
Derived from: `main.go` (route registrations) and `runbooks/health.md`.

---

## Health

| Method | Path     | Description                                     | Status              |
|--------|----------|-------------------------------------------------|---------------------|
| GET    | /healthz | Liveness probe — returns `{"status":"ok"}` 200 | Not yet implemented |

> Specified in `runbooks/health.md`; must be wired in `main.go` before next deployment gate.

---

## Auth

| Method | Path          | Description                                                    |
|--------|---------------|----------------------------------------------------------------|
| POST   | /auth/login   | Authenticate with email + password; returns a signed JWT token |
| POST   | /auth/logout  | Invalidate the current session; returns 204 No Content         |
| POST   | /auth/refresh | Exchange a valid token for a fresh JWT token                   |

---

## Users

| Method | Path          | Description                              |
|--------|---------------|------------------------------------------|
| GET    | /users        | List all users                           |
| POST   | /users        | Create a new user                        |
| GET    | /users/{id}   | Retrieve a single user by ID             |
| PUT    | /users/{id}   | Replace / update a user record by ID     |
| DELETE | /users/{id}   | Delete a user by ID; returns 204         |

---

## Orders

| Method | Path                | Description                                          |
|--------|---------------------|------------------------------------------------------|
| GET    | /orders             | List all orders                                      |
| POST   | /orders             | Create a new order                                   |
| GET    | /orders/{id}        | Retrieve a single order by ID                        |
| PUT    | /orders/{id}        | Replace / update an order by ID                      |
| DELETE | /orders/{id}        | Delete an order by ID; returns 204                   |
| GET    | /users/{id}/orders  | List all orders belonging to a specific user         |

---

## Summary

| Domain  | Endpoint count | Notes                                      |
|---------|----------------|--------------------------------------------|
| Health  | 1              | Specified but not yet wired in `main.go`   |
| Auth    | 3              |                                            |
| Users   | 5              |                                            |
| Orders  | 6              | Includes nested route under `/users/{id}`  |
| **Total** | **15**       |                                            |

---

## Gaps & follow-up items

1. **`GET /healthz` not implemented** — `runbooks/health.md` specifies it; add a dependency-free handler to `main.go` returning `{"status":"ok"}` HTTP 200.
2. **No API versioning prefix** — all paths are unversioned (`/users`, not `/v1/users`). Agree on a versioning strategy before public release.
3. **No authentication middleware** — no routes currently enforce token validation. Auth requirements per endpoint must be specified before the security review gate.
4. **List endpoint contracts undefined** — `GET /users` and `GET /orders` have no documented pagination or filtering parameters; surface in the next spec review.
