package main

import (
	"encoding/json"
	"net/http"
)

func versionHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{"version": "0.1.0"})
}

func newMux() *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/version", versionHandler)
	return mux
}

func main() {
	http.ListenAndServe(":8080", newMux())
}
