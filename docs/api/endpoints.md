# API Endpoint Reference: `/health`, `/version`, `/metrics`

## Overview

These three endpoints are available on every Nexocloud service instance. They are read-only, expose no user data, and are used by monitoring infrastructure, CI pipelines, and on-call tooling.

---

## Authentication

All three endpoints are **unauthenticated**. They must be reachable from internal network ranges without a bearer token or API key. Do not place them behind your service's main auth middleware.

If your service enforces mTLS at the network edge, these endpoints are still accessible to internal probes that present the cluster's internal CA-signed certificate.

---

## `GET /health`

Returns the current liveness and readiness state of the service.

### Request

```
GET /health HTTP/1.1
Host: <service-host>
```

No query parameters. No request body.

### Response — 200 OK (healthy)

```json
{
  "status": "ok",
  "checks": {
    "database": "ok",
    "cache":    "ok",
    "upstream": "ok"
  },
  "timestamp": "2026-06-22T14:05:00Z"
}
```

| Field | Type | Description |
|---|---|---|
| `status` | `string` | Top-level aggregate. Always `"ok"` or `"degraded"` or `"unhealthy"`. |
| `checks` | `object` | Map of dependency name → `"ok"` \| `"degraded"` \| `"unhealthy"`. Keys vary by service. |
| `timestamp` | `string (ISO 8601)` | Server time at evaluation. |

### Response — 200 OK (degraded)

When one or more non-critical dependencies are impaired but the service can still handle traffic, `status` is `"degraded"` and the top-level HTTP code remains **200** so load balancers keep the instance in rotation.

```json
{
  "status": "degraded",
  "checks": {
    "database": "ok",
    "cache":    "degraded",
    "upstream": "ok"
  },
  "timestamp": "2026-06-22T14:05:00Z"
}
```

### Response — 503 Service Unavailable (unhealthy)

When the service cannot handle traffic (e.g., cannot reach its primary database), it returns HTTP **503** with `status: "unhealthy"`. Load balancers and readiness probes must remove the instance from rotation when they see 503.

```json
{
  "status": "unhealthy",
  "checks": {
    "database": "unhealthy",
    "cache":    "ok",
    "upstream": "ok"
  },
  "timestamp": "2026-06-22T14:05:00Z"
}
```

### Error Codes

| HTTP Status | Meaning |
|---|---|
| `200` | Healthy or degraded — instance accepts traffic. |
| `503` | Unhealthy — instance should be removed from rotation. |
| `405` | Method not allowed (only GET is supported). |

### Example cURL

```bash
curl -sf http://localhost:8080/health | jq .
```

### Design Notes

- The handler must be **dependency-free** in its own execution path; it only calls out to check dependencies, it does not itself depend on them to respond.
- Response time must be under **200 ms**; if a dependency check exceeds that budget, mark it `"degraded"` rather than blocking.
- No caching: always evaluate live at request time.

---

## `GET /version`

Returns the deployed artifact version and build metadata.

### Request

```
GET /version HTTP/1.1
Host: <service-host>
```

No query parameters. No request body.

### Response — 200 OK

```json
{
  "service":    "nexocloud-gateway",
  "version":    "1.14.3",
  "commit":     "a3f92c1",
  "build_time": "2026-06-20T09:12:44Z",
  "go_version": "go1.22.4"
}
```

| Field | Type | Description |
|---|---|---|
| `service` | `string` | Canonical service name as registered in the service catalog. |
| `version` | `string` | Semantic version (`MAJOR.MINOR.PATCH`). |
| `commit` | `string` | Short Git SHA of the HEAD commit baked into the build. |
| `build_time` | `string (ISO 8601)` | UTC timestamp when the artifact was compiled. |
| `go_version` | `string` | Runtime version (language/runtime field name varies by stack: `go_version`, `python_version`, `node_version`, etc.). |

### Error Codes

| HTTP Status | Meaning |
|---|---|
| `200` | Always returned when the service is up. |
| `405` | Method not allowed. |

### Example cURL

```bash
curl -s http://localhost:8080/version | jq .version
```

### Design Notes

- All fields are baked into the binary at build time via linker flags or environment injection; there are no runtime lookups.
- The endpoint always returns 200 as long as the process is alive. It carries no liveness semantics.

---

## `GET /metrics`

Returns Prometheus-format metrics for scraping by the monitoring stack.

### Request

```
GET /metrics HTTP/1.1
Host: <service-host>
```

No query parameters. No request body.

The response content type is `text/plain; version=0.0.4; charset=utf-8` (standard Prometheus exposition format). Do not request `application/json` — it is not supported.

### Response — 200 OK

```
# HELP process_cpu_seconds_total Total user and system CPU time spent in seconds.
# TYPE process_cpu_seconds_total counter
process_cpu_seconds_total 4.32

# HELP http_requests_total Total HTTP requests received.
# TYPE http_requests_total counter
http_requests_total{method="GET",status="200",path="/health"} 1024
http_requests_total{method="POST",status="500",path="/v1/infer"} 3

# HELP http_request_duration_seconds HTTP request latency histogram.
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{le="0.005"} 800
http_request_duration_seconds_bucket{le="0.01"}  900
http_request_duration_seconds_bucket{le="0.025"} 960
http_request_duration_seconds_bucket{le="0.05"}  980
http_request_duration_seconds_bucket{le="+Inf"}  1024
http_request_duration_seconds_sum   5.12
http_request_duration_seconds_count 1024

# HELP api_budget_used_usd Current month spend per API lane in USD.
# TYPE api_budget_used_usd gauge
api_budget_used_usd{lane="anthropic"} 312.50
api_budget_used_usd{lane="openai"}    198.00
api_budget_used_usd{lane="google"}    275.10

# HELP api_budget_limit_usd Configured monthly budget ceiling per API lane in USD.
# TYPE api_budget_limit_usd gauge
api_budget_limit_usd{lane="anthropic"} 500
api_budget_limit_usd{lane="openai"}    300
api_budget_limit_usd{lane="google"}    400
```

#### Standard metric families

| Metric | Type | Description |
|---|---|---|
| `process_cpu_seconds_total` | Counter | Cumulative CPU time consumed by the process. |
| `process_resident_memory_bytes` | Gauge | Current RSS in bytes. |
| `http_requests_total` | Counter | Total requests labelled by `method`, `status`, `path`. |
| `http_request_duration_seconds` | Histogram | Request latency with standard bucket boundaries. |
| `api_budget_used_usd` | Gauge | Month-to-date spend per API lane (`anthropic`, `openai`, `google`). |
| `api_budget_limit_usd` | Gauge | Configured monthly ceiling per API lane. |

### Error Codes

| HTTP Status | Meaning |
|---|---|
| `200` | Metrics payload returned. |
| `405` | Method not allowed. |
| `500` | Internal error generating metrics (treat as a service alert). |

### Example cURL

```bash
curl -s http://localhost:8080/metrics | grep api_budget
```

### Example Prometheus scrape config

```yaml
scrape_configs:
  - job_name: nexocloud-gateway
    static_configs:
      - targets: ['nexocloud-gateway:8080']
    metrics_path: /metrics
    scrape_interval: 15s
```

### Design Notes

- The `/metrics` endpoint is served by the same HTTP server process as the application. It is not a separate sidecar.
- Histograms use the default Go client bucket boundaries; do not change them without coordinating with the observability team, as existing recording rules depend on them.
- `api_budget_used_usd` is refreshed every 60 seconds from the Paperclip billing API. A stale gauge (unchanged for > 5 minutes) indicates a Paperclip connectivity problem, not zero spend.