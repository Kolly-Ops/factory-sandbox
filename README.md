# factory-sandbox

[![CI](https://github.com/billyronks/factory-sandbox/actions/workflows/ci.yml/badge.svg)](https://github.com/billyronks/factory-sandbox/actions)

Target service for the Agent Factory. The factory's agents modify this repo.

## Endpoints

- `GET /version` — returns `{"version":"0.1.0","commit":"..."}`

## Usage

```bash
make test    # run tests
make build   # compile binary
make run     # build and run
```
