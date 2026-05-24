.PHONY: test build run

test:
	go test ./... -v

build:
	go build -ldflags="-X main.commit=$$(git rev-parse --short HEAD)" -o bff-sample .

run: build
	./bff-sample
