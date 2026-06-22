package main

import (
"encoding/json"
"net/http"
"net/http/httptest"
"regexp"
"strconv"
"strings"
"testing"
)

func callHandler(handler http.HandlerFunc, method, target string) *httptest.ResponseRecorder {
w := httptest.NewRecorder()
handler(w, httptest.NewRequest(method, target, nil))
return w
}

func newMux() *http.ServeMux {
mux := http.NewServeMux()
mux.HandleFunc("/health", healthHandler)
mux.HandleFunc("/version", versionHandler)
mux.HandleFunc("/metrics", metricsHandler)
return mux
}

// ── /health ──────────────────────────────────────────────────────────────────

func TestHealth_GET_Returns200(t *testing.T) {
w := callHandler(healthHandler, http.MethodGet, "/health")
if w.Code != http.StatusOK {
t.Errorf("expected 200, got %d", w.Code)
}
}

func TestHealth_ContentTypeIsJSON(t *testing.T) {
w := callHandler(healthHandler, http.MethodGet, "/health")
ct := w.Header().Get("Content-Type")
if !strings.HasPrefix(ct, "application/json") {
t.Errorf("expected application/json Content-Type, got %q", ct)
}
}

func TestHealth_BodyIsValidJSON(t *testing.T) {
w := callHandler(healthHandler, http.MethodGet, "/health")
var body map[string]string
if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
t.Fatalf("body is not valid JSON: %v", err)
}
}

func TestHealth_StatusFieldIsOk(t *testing.T) {
w := callHandler(healthHandler, http.MethodGet, "/health")
var body map[string]string
if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
t.Fatalf("could not decode body: %v", err)
}
if body["status"] != "ok" {
t.Errorf("expected status 'ok', got %q", body["status"])
}
}

func TestHealth_NoExtraFields(t *testing.T) {
w := callHandler(healthHandler, http.MethodGet, "/health")
var body map[string]string
if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
t.Fatalf("could not decode body: %v", err)
}
for k := range body {
if k != "status" {
t.Errorf("unexpected field %q in /health response", k)
}
}
}

func TestHealth_NonGETReturns405(t *testing.T) {
for _, m := range []string{
http.MethodPost, http.MethodPut, http.MethodDelete,
http.MethodPatch, http.MethodHead,
} {
t.Run(m, func(t *testing.T) {
w := callHandler(healthHandler, m, "/health")
if w.Code != http.StatusMethodNotAllowed {
t.Errorf("%s /health: expected 405, got %d", m, w.Code)
}
})
}
}

// ── /version ─────────────────────────────────────────────────────────────────

func TestVersion_GET_Returns200(t *testing.T) {
w := callHandler(versionHandler, http.MethodGet, "/version")
if w.Code != http.StatusOK {
t.Errorf("expected 200, got %d", w.Code)
}
}

func TestVersion_ContentTypeIsJSON(t *testing.T) {
w := callHandler(versionHandler, http.MethodGet, "/version")
ct := w.Header().Get("Content-Type")
if !strings.HasPrefix(ct, "application/json") {
t.Errorf("expected application/json Content-Type, got %q", ct)
}
}

func TestVersion_BodyIsValidJSON(t *testing.T) {
w := callHandler(versionHandler, http.MethodGet, "/version")
var body map[string]string
if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
t.Fatalf("body is not valid JSON: %v", err)
}
}

func TestVersion_VersionFieldPresent(t *testing.T) {
w := callHandler(versionHandler, http.MethodGet, "/version")
var body map[string]string
if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
t.Fatalf("could not decode body: %v", err)
}
if _, ok := body["version"]; !ok {
t.Error("missing required field 'version'")
}
}

func TestVersion_VersionNonEmpty(t *testing.T) {
w := callHandler(versionHandler, http.MethodGet, "/version")
var body map[string]string
if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
t.Fatalf("could not decode body: %v", err)
}
if body["version"] == "" {
t.Error("version field must not be empty")
}
}

func TestVersion_VersionMatchesSemver(t *testing.T) {
w := callHandler(versionHandler, http.MethodGet, "/version")
var body map[string]string
if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
t.Fatalf("could not decode body: %v", err)
}
semverRE := regexp.MustCompile(`^\d+\.\d+\.\d+`)
if !semverRE.MatchString(body["version"]) {
t.Errorf("version %q does not conform to MAJOR.MINOR.PATCH semver", body["version"])
}
}

func TestVersion_NoExtraFields(t *testing.T) {
w := callHandler(versionHandler, http.MethodGet, "/version")
var body map[string]string
if err := json.NewDecoder(w.Body).Decode(&body); err != nil {
t.Fatalf("could not decode body: %v", err)
}
for k := range body {
if k != "version" {
t.Errorf("unexpected field %q in /version response", k)
}
}
}

func TestVersion_NonGETReturns405(t *testing.T) {
for _, m := range []string{
http.MethodPost, http.MethodPut, http.MethodDelete,
http.MethodPatch, http.MethodHead,
} {
t.Run(m, func(t *testing.T) {
w := callHandler(versionHandler, m, "/version")
if w.Code != http.StatusMethodNotAllowed {
t.Errorf("%s /version: expected 405, got %d", m, w.Code)
}
})
}
}

// ── /metrics ─────────────────────────────────────────────────────────────────

func TestMetrics_GET_Returns200(t *testing.T) {
w := callHandler(metricsHandler, http.MethodGet, "/metrics")
if w.Code != http.StatusOK {
t.Errorf("expected 200, got %d", w.Code)
}
}

func TestMetrics_ContentTypeIsTextPlain(t *testing.T) {
w := callHandler(metricsHandler, http.MethodGet, "/metrics")
ct := w.Header().Get("Content-Type")
if !strings.HasPrefix(ct, "text/plain") {
t.Errorf("expected text/plain Content-Type, got %q", ct)
}
}

func TestMetrics_ContainsRequestsTotal(t *testing.T) {
w := callHandler(metricsHandler, http.MethodGet, "/metrics")
body := w.Body.String()
if !strings.Contains(body, "requests_total") {
t.Errorf("metrics output missing required key 'requests_total'; got: %q", body)
}
}

func TestMetrics_RequestsTotalIsNumeric(t *testing.T) {
w := callHandler(metricsHandler, http.MethodGet, "/metrics")
for _, line := range strings.Split(strings.TrimSpace(w.Body.String()), "\n") {
if line == "" || strings.HasPrefix(line, "#") {
continue
}
parts := strings.Fields(line)
if len(parts) < 2 {
t.Errorf("malformed metric line (expected 'key value'): %q", line)
continue
}
if _, err := strconv.ParseFloat(parts[1], 64); err != nil {
t.Errorf("metric %q has non-numeric value %q", parts[0], parts[1])
}
}
}

func TestMetrics_NonGETReturns405(t *testing.T) {
for _, m := range []string{
http.MethodPost, http.MethodPut, http.MethodDelete,
http.MethodPatch, http.MethodHead,
} {
t.Run(m, func(t *testing.T) {
w := callHandler(metricsHandler, m, "/metrics")
if w.Code != http.StatusMethodNotAllowed {
t.Errorf("%s /metrics: expected 405, got %d", m, w.Code)
}
})
}
}

// ── negative / edge-case scenarios ───────────────────────────────────────────

func TestUnknownRoute_Returns404(t *testing.T) {
mux := newMux()
for _, path := range []string{"/nonexistent", "/healthz", "/status", "/api/health"} {
t.Run(path, func(t *testing.T) {
req := httptest.NewRequest(http.MethodGet, path, nil)
w := httptest.NewRecorder()
mux.ServeHTTP(w, req)
if w.Code != http.StatusNotFound {
t.Errorf("%q: expected 404, got %d", path, w.Code)
}
})
}
}

func TestRoutesCaseSensitive_Returns404(t *testing.T) {
mux := newMux()
for _, path := range []string{"/Health", "/HEALTH", "/Version", "/Metrics", "/METRICS"} {
t.Run(path, func(t *testing.T) {
req := httptest.NewRequest(http.MethodGet, path, nil)
w := httptest.NewRecorder()
mux.ServeHTTP(w, req)
if w.Code != http.StatusNotFound {
t.Errorf("%q: expected 404 (routes are case-sensitive), got %d", path, w.Code)
}
})
}
}
