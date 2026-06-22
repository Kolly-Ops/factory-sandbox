package main

import (
"encoding/json"
"fmt"
"net/http"
"runtime"
"time"
)

var (
version   = "dev"
startTime = time.Now()
)

func healthHandler(w http.ResponseWriter, r *http.Request) {
if r.Method != http.MethodGet {
http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
return
}
w.Header().Set("Content-Type", "application/json")
json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func versionHandler(w http.ResponseWriter, r *http.Request) {
if r.Method != http.MethodGet {
http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
return
}
w.Header().Set("Content-Type", "application/json")
json.NewEncoder(w).Encode(map[string]string{"version": version})
}

func metricsHandler(w http.ResponseWriter, r *http.Request) {
if r.Method != http.MethodGet {
http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
return
}
var mem runtime.MemStats
runtime.ReadMemStats(&mem)
w.Header().Set("Content-Type", "application/json")
json.NewEncoder(w).Encode(map[string]any{
"goroutines":  runtime.NumGoroutine(),
"alloc_bytes": mem.Alloc,
"sys_bytes":   mem.Sys,
"uptime_sec":  time.Since(startTime).Seconds(),
})
}

func newMux() *http.ServeMux {
mux := http.NewServeMux()
mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
fmt.Fprintln(w, "Hello, World!")
})
mux.HandleFunc("/health", healthHandler)
mux.HandleFunc("/version", versionHandler)
mux.HandleFunc("/metrics", metricsHandler)
return mux
}

func main() {
http.ListenAndServe(":8080", newMux())
}
