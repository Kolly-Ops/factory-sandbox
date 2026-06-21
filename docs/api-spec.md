# HTTP Endpoint Specification: /healthz and /version

Both endpoints are unauthenticated, read-only, and return JSON. They must be reachable without credentials so that infrastructure tooling (liveness probes, deployment pipelines) can call them freely.

---

## GET /healthz

**Purpose:** Liveness probe. Confirms the process is running and able to serve requests.

### Request

| Field   | Value      |
|---------|------------|
| Method  | `GET`      |
| Path    | `/healthz` |
| Headers | none required |
| Body    | none       |

### Response

**Status code:** `200 OK`

**Response headers:**

| Header         | Value              |
|----------------|--------------------|
| `Content-Type` | `application/json` |

**Response body:**

```json
{
  "status": "ok",
  "uptime": "72h14m5s"
}
```

| Field    | Type   | Always present | Description |
|----------|--------|----------------|-------------|
| `status` | string | yes | Fixed value `"ok"`. |
| `uptime` | string | yes | How long the process has been running, formatted as Go `time.Duration.String()` (e.g. `"72h14m5s"`). |

---

## GET /version

**Purpose:** Exposes version and build metadata for deployment auditing and debugging.

### Request

| Field   | Value      |
|---------|------------|
| Method  | `GET`      |
| Path    | `/version` |
| Headers | none required |
| Body    | none       |

### Response

**Status code:** `200 OK`

**Response headers:**

| Header         | Value              |
|----------------|--------------------|
| `Content-Type` | `application/json` |

**Response body:**

```json
{
  "version": "1.2.3",
  "commit": "abc1234f",
  "build_time": "2026-06-21T10:00:00Z"
}
```

| Field        | Type   | Always present | Description |
|--------------|--------|----------------|-------------|
| `version`    | string | yes | Semantic version string (e.g. `"1.2.3"`). Defaults to `"dev"` when not injected at build time. |
| `commit`     | string | yes | Short Git SHA (8 hex characters). Defaults to `"unknown"` when not injected at build time. |
| `build_time` | string | yes | RFC 3339 UTC timestamp of when the binary was compiled. Defaults to `"unknown"` when not injected at build time. |

Build-time values are injected via `-ldflags`:

```
-X 'github.com/example/app/internal/api.Version=1.2.3'
-X 'github.com/example/app/internal/api.Commit=abc1234f'
-X 'github.com/example/app/internal/api.BuildTime=2026-06-21T10:00:00Z'
```

---

## Method Enforcement

Both endpoints accept `GET` only. Any other method must return:

**Status code:** `405 Method Not Allowed`

**Response headers:**

| Header  | Value |
|---------|-------|
| `Allow` | `GET` |

No response body.

> Go 1.22's `http.ServeMux` supports method-prefixed patterns (`GET /healthz`), which enforces this automatically and sets the `Allow` header.