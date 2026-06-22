package main

import (
	"errors"
	"sync"
)

const alertThreshold = 0.80

type Budget struct {
	Lane  string  `json:"lane"`
	Limit float64 `json:"limit"`
	Spent float64 `json:"spent"`
}

type CreateBudgetRequest struct {
	Lane  string  `json:"lane"`
	Limit float64 `json:"limit"`
}

type CheckBudgetRequest struct {
	Lane  string  `json:"lane"`
	Spend float64 `json:"spend"`
}

type CheckBudgetResult struct {
	Lane    string  `json:"lane"`
	Limit   float64 `json:"limit"`
	Spent   float64 `json:"spent"`
	Alert   bool    `json:"alert"`
	Exceeds bool    `json:"exceeds"`
}

var (
	mu    sync.RWMutex
	store = map[string]*Budget{}
)

func resetStore() {
	mu.Lock()
	defer mu.Unlock()
	store = map[string]*Budget{}
}

func ListBudgets() []*Budget {
	mu.RLock()
	defer mu.RUnlock()
	result := make([]*Budget, 0, len(store))
	for _, b := range store {
		result = append(result, b)
	}
	return result
}

func CreateBudget(req CreateBudgetRequest) (*Budget, error) {
	if req.Lane == "" {
		return nil, errors.New("lane is required")
	}
	if req.Limit <= 0 {
		return nil, errors.New("limit must be positive")
	}
	mu.Lock()
	defer mu.Unlock()
	if _, exists := store[req.Lane]; exists {
		return nil, errors.New("budget for lane already exists")
	}
	b := &Budget{Lane: req.Lane, Limit: req.Limit}
	store[req.Lane] = b
	return b, nil
}

func CheckBudget(req CheckBudgetRequest) (*CheckBudgetResult, error) {
	mu.RLock()
	defer mu.RUnlock()
	b, ok := store[req.Lane]
	if !ok {
		return nil, errors.New("budget not found")
	}
	projected := b.Spent + req.Spend
	exceeds := projected > b.Limit
	alert := !exceeds && projected/b.Limit >= alertThreshold
	return &CheckBudgetResult{
		Lane:    b.Lane,
		Limit:   b.Limit,
		Spent:   b.Spent,
		Alert:   alert,
		Exceeds: exceeds,
	}, nil
}