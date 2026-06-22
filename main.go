package main

import (
"encoding/json"
"fmt"
"net/http"
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
json.NewEncoder(w).Encode(map[string]string{"version": "1.0.0"})
}

func metricsHandler(w http.ResponseWriter, r *http.Request) {
if r.Method != http.MethodGet {
http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
return
}
w.Header().Set("Content-Type", "text/plain")
fmt.Fprintln(w, "requests_total 42")
}

func main() {
http.HandleFunc("/health", healthHandler)
http.HandleFunc("/version", versionHandler)
http.HandleFunc("/metrics", metricsHandler)
http.ListenAndServe(":8080", nil)
}
