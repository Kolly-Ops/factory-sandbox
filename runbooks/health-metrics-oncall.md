# Operational Runbook: Health, Metrics, and On-Call Response

**Audience:** On-call engineers, SREs  
**Scope:** Nexocloud services exposing `/health`, `/version`, and `/metrics`  
**Last reviewed:** 2026-06-22

---

## 1. Reading `/health` Output

The `/health` endpoint returns a top-level `status` field and a per-dependency `checks` map.

| `status` value | HTTP code | Meaning | Action |
|---|---|---|---|
| `ok` | 200 | All checks pass. Service is fully healthy. | No action needed. |
| `degraded` | 200 | One or more non-critical dependencies are impaired. Service is still handling traffic. | Open a P3 ticket; investigate within 1 business day. |
| `unhealthy` | 503 | A critical dependency has failed. Service has removed itself from rotation (or will be removed by the load balancer). | Page on-call immediately. See §4. |

### Interpreting individual `checks`

Each key under `checks` maps to a named dependency. Common keys:

| Key | What it monitors |
|---|---|
| `database` | Primary relational DB reachability and query execution |
| `cache` | Redis/Memcache ping |
| `upstream` | Outbound HTTP to critical upstream APIs (Paperclip, Anthropic, etc.) |

If a check is `"degraded"`, the service is imposing a timeout-based fallback. If it is `"unhealthy"`, the service has lost connectivity or is receiving persistent errors from that dependency.

---

## 2. Interpreting `/metrics` Output

### 2.1 Latency (SLO basis)

```
http_request_duration_seconds_bucket
```

Calculate p99 latency with:

```promql
histogram_quantile(0.99,
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le, path)
)
```

**Baseline expectations:**

| Path | p50 target | p99 target |
|---|---|---|
| `/health` | < 10 ms | < 50 ms |
| `/v1/infer` (typical) | < 800 ms | < 3 s |

### 2.2 Error rate

```promql
sum(rate(http_requests_total{status=~"5.."}[5m])) by (path)
/
sum(rate(http_requests_total[5m])) by (path)
```

Alert if error rate exceeds **1% over 5 minutes** on any path.

### 2.3 API budget gauges

The `api_budget_used_usd` and `api_budget_limit_usd` gauges track per-lane spend.

```promql
api_budget_used_usd / api_budget_limit_usd
```

| Ratio | Meaning |
|---|---|
| < 0.80 | Normal. |
| ≥ 0.80 | **Alert threshold.** Paperclip fires a notification at 80%. Investigate spend growth. |
| = 1.00 | Budget ceiling. Paperclip blocks further calls on that lane. Service will return errors for affected lane. |

Monthly lane ceilings (from `docs/budgets.md`):

| Lane | Ceiling (USD/month) |
|---|---|
| Anthropic | 500 |
| OpenAI | 300 |
| Google | 400 |

**Paperclip never auto-exceeds the ceiling.** When the ceiling is hit, calls on that lane return a 402-equivalent error. Plan for this in on-call response (see §4.4).

### 2.4 Detecting a stale metrics scrape

If `api_budget_used_usd` has not changed in > 5 minutes, the gauge is stale — Paperclip is unreachable. Treat as a P2 incident.

---

## 3. Alert Thresholds

| Alert name | Condition | Severity | Initial response |
|---|---|---|---|
| `HealthEndpointUnhealthy` | `/health` returns 503 for > 1 minute | P1 | Page on-call. Follow §4. |
| `HealthEndpointDegraded` | `/health` `status == "degraded"` for > 10 minutes | P3 | Ticket; investigate next business day. |
| `HighErrorRate` | 5xx rate > 1% over 5 minutes | P2 | Page on-call. |
| `HighP99Latency` | p99 latency > 3 s over 5 minutes | P2 | Page on-call. |
| `ApiBudget80Pct` | `api_budget_used_usd / api_budget_limit_usd >= 0.8` | P2 | Notify eng lead and AI CEO Atlas; review spend within 4 hours. |
| `ApiBudgetExhausted` | ratio = 1.0 | P1 | Page on-call. Calls on that lane are blocked. |
| `MetricsScrapeStale` | `api_budget_used_usd` unchanged for > 5 minutes | P2 | Check Paperclip connectivity. |
| `HealthEndpointSlow` | `/health` p99 > 200 ms | P3 | Investigate dependency check timeouts. |

Alerts are routed through PagerDuty. P1 and P2 pages go to the on-call engineer; P3 creates a ticket.

---

## 4. On-Call Response Guides

### 4.1 `HealthEndpointUnhealthy` — service returning 503

**Symptoms:** `/health` returns 503. Load balancer has removed instance(s) from rotation. Users may see errors or slowdowns if all instances are unhealthy.

**Steps:**

1. Check which `checks` key is `"unhealthy"`:
   ```bash
   curl -s https://<service-host>/health | jq .checks
   ```

2. **If `database` is unhealthy:**
   - Check DB reachability from the service pod:
     ```bash
     kubectl exec -it <pod> -- nc -zv <db-host> 5432
     ```
   - Check DB server metrics in Grafana. Look for connection pool exhaustion, OOM, or disk full.
   - If DB is reachable but queries fail, check for long-running locks:
     ```sql
     SELECT pid, query, state, wait_event FROM pg_stat_activity WHERE state != 'idle';
     ```
   - Escalate to DBA on-call if the issue is not resolved within 10 minutes.

3. **If `cache` is unhealthy:**
   - A cache outage alone should not cause a 503 (cache is typically non-critical). If it does, the service configuration is incorrect — flag to the owning team.
   - Flush and restart the cache if it is a single-node Redis with no replicas.

4. **If `upstream` is unhealthy:**
   - Identify which upstream is failing (check service logs for the specific host).
   - Check the upstream's own status page or `/health`.
   - If the upstream is a Nexocloud internal service, page its owning team.
   - If it is an external API (Anthropic, OpenAI, Google), check their public status pages and activate the fallback lane if one is configured.

5. Once the root cause is resolved, verify recovery:
   ```bash
   watch -n5 'curl -s https://<service-host>/health | jq .status'
   ```
   The load balancer will return the instance to rotation automatically when it sees HTTP 200.

6. Write an incident summary in the incident channel within 24 hours.

---

### 4.2 `HighErrorRate` — elevated 5xx responses

**Steps:**

1. Identify which paths are affected:
   ```promql
   sum by (path) (rate(http_requests_total{status=~"5.."}[5m]))
   ```

2. Pull recent error logs from the affected service:
   ```bash
   kubectl logs -l app=<service> --since=10m | grep '"level":"error"'
   ```

3. If errors are concentrated on a single path and related to an upstream (e.g., Anthropic API), check the budget gauges (see §4.4) and upstream status.

4. If errors are widespread across paths, suspect a deployment. Check recent rollouts:
   ```bash
   kubectl rollout history deployment/<service>
   ```
   Roll back if the elevated error rate began at deploy time:
   ```bash
   kubectl rollout undo deployment/<service>
   ```

5. If the cause is not a bad deploy and not an upstream, escalate to the service owner.

---

### 4.3 `HighP99Latency` — tail latency spike

**Steps:**

1. Narrow the affected path:
   ```promql
   histogram_quantile(0.99,
     sum(rate(http_request_duration_seconds_bucket[5m])) by (le, path)
   )
   ```

2. Check if `/health` itself is slow (`HealthEndpointSlow` alert). A slow health check suggests dependency checks are timing out, which also inflates apparent latency for the service.

3. Check database slow query log for queries > 500 ms.

4. Check if a recent code change introduced an N+1 query or a synchronous call inside a hot path. Review the commit that went out closest to the latency onset.

5. Check pod resource saturation (CPU throttling, memory pressure):
   ```bash
   kubectl top pods -l app=<service>
   ```

6. If the pod is CPU-throttled, add a replica or raise the CPU limit (requires team lead approval for production).

---

### 4.4 `ApiBudget80Pct` or `ApiBudgetExhausted` — API spend alert

**Context:** Nexocloud API budgets are enforced by Paperclip. At 80% of the monthly ceiling, Paperclip sends an alert but **does not block traffic**. At 100%, Paperclip blocks all further calls on that lane for the remainder of the month. Paperclip **never auto-exceeds** the ceiling.

**At 80% threshold (P2):**

1. Identify which lane is at risk:
   ```promql
   api_budget_used_usd / api_budget_limit_usd
   ```

2. Notify the engineering lead and AI CEO Atlas via the `#budget-alerts` Slack channel within 4 hours. Include: lane name, current spend, days remaining in the month, projected end-of-month spend at current burn rate.

3. Project end-of-month spend:
   ```
   projected = current_spend / days_elapsed * total_days_in_month
   ```

4. If projected spend exceeds the ceiling, work with the engineering lead and Atlas to either:
   - Reduce call volume (disable non-essential features using that lane), or
   - Request a budget increase, which requires approval from the human Co-CEO (L4 gate in the Nexocloud org model).

**At 100% (lane exhausted, P1):**

1. Page on-call. The lane is blocked; all calls to it return errors.
2. Activate the designated fallback lane if the service supports lane failover (check service README for `FALLBACK_LANE` configuration).
3. If no fallback exists, disable features that depend on the exhausted lane and communicate user impact.
4. Do not attempt to exceed the ceiling; Paperclip will not allow it and attempting workarounds violates policy.
5. Budget resets at the start of the next calendar month. No manual reset is available.
6. Flag to the human Co-CEO for budget limit review within 24 hours.

---

### 4.5 `MetricsScrapeStale` — Paperclip unreachable

**Symptoms:** `api_budget_used_usd` gauge value has not changed for > 5 minutes.

**Steps:**

1. Check outbound connectivity from the service to Paperclip:
   ```bash
   kubectl exec -it <pod> -- curl -sf https://paperclip.internal/health
   ```

2. Check Paperclip's own health status in its runbook.

3. If Paperclip is down, the service continues to function but budget enforcement is suspended — calls on all lanes will proceed without ceiling enforcement until Paperclip recovers. This is an acceptable temporary state but must be resolved quickly to avoid unintended spend.

4. Escalate to the Paperclip owning team immediately.

---

## 5. Useful Commands Reference

```bash
# Live health check with auto-refresh
watch -n5 'curl -s http://localhost:8080/health | jq .'

# Deployed version of a running pod
curl -s http://localhost:8080/version | jq '{version, commit}'

# Current API budget utilization
curl -s http://localhost:8080/metrics | grep api_budget

# Tail error logs for a service
kubectl logs -l app=<service> --since=5m -f | grep '"level":"error"'

# List recent deployments
kubectl rollout history deployment/<service>

# Roll back one revision
kubectl rollout undo deployment/<service>

# Check resource usage
kubectl top pods -l app=<service>
```

---

## 6. Escalation Path

| Situation | Escalate to |
|---|---|
| DB outage | DBA on-call |
| Internal upstream down | Owning team on-call |
| External API (Anthropic / OpenAI / Google) down | Check public status page; activate fallback lane |
| Budget 80% threshold | Engineering lead + AI CEO Atlas (within 4 hours) |
| Budget exhausted | Human Co-CEO (L4 gate) for limit increase |
| Paperclip unreachable | Paperclip team on-call |
| Unresolved P1 after 20 minutes | Escalate to engineering lead |