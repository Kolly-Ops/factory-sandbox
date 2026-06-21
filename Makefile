.PHONY: test build run

test:
	go test ./...

build:
	go build -o factory-sandbox .

run: build
	./factory-sandbox
