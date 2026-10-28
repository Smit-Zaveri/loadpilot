# LoadPilot

Self-hosted load and performance testing for HTTP and LLM APIs, with a live web UI.

> **Status: early development (pre-alpha).** The load engine, CLI and demo target work today.
> The web UI, history, scenarios and LLM metrics are next. See [PLAN.md](PLAN.md) for the roadmap.

## Why LoadPilot

- **Honest numbers.** Open-model tests measure latency from the *planned* send time, so a stalled
  server can't hide its queueing delay (coordinated omission). LoadPilot also warns when the load
  generator itself is the bottleneck.
- **Two load models.** A fixed number of virtual users (closed) or a fixed arrival rate (open),
  with linear ramps between stages.
- **Built-in demo target.** Try everything locally against endpoints with adjustable latency,
  errors, rate limits (429) and a fake streaming LLM.
- **Self-hosted, no telemetry.** Your traffic and results stay on your machine.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync

# Terminal 1: start the demo target
uv run loadpilot demo-server

# Terminal 2: 20 virtual users for 10 seconds
uv run loadpilot run --url http://127.0.0.1:8090/random-latency --vus 20 --duration 10s

# Fixed arrival rate: 200 requests per second
uv run loadpilot run --url "http://127.0.0.1:8090/slow?ms=100" --rate 200 --duration 10s

# From a YAML file, saving full results
uv run loadpilot run ../examples/ramp.yaml --out results.json
```

Press `Ctrl+C` once to stop gracefully, twice to abort.

## Test files

```yaml
name: ramp-up
warmup: 5s                  # left out of the summary
load:
  mode: vus                 # vus = virtual users, rate = iterations per second
  stages:
    - { duration: 10s, target: 20 }   # ramp 0 → 20
    - { duration: 20s, target: 20 }   # hold
    - { duration: 5s,  target: 0 }    # ramp down
steps:
  - name: list
    request:
      url: http://127.0.0.1:8090/random-latency
      params: { min_ms: 10, max_ms: 80 }
  - name: create
    request:
      method: POST
      url: http://127.0.0.1:8090/echo
      json: { title: hello }
      timeout: 5s
```

Shorthand for a single request: `request: {...}` instead of `steps`, and
`load: {vus: 10, duration: 30s}` or `load: {rate: 100, duration: 1m}` instead of `stages`.
More examples are in [`examples/`](examples).

## Demo target endpoints

| Endpoint | Behaviour |
|----------|-----------|
| `GET /fast` | Responds immediately |
| `GET /slow?ms=200` | Fixed delay |
| `GET /random-latency?min_ms=10&max_ms=500` | Uniform random delay |
| `GET /flaky?error_rate=0.1` | Returns 500 with the given probability |
| `GET /status/{code}` | Returns any status code |
| `GET /rate-limited` | Token bucket; 429 + `Retry-After` when empty |
| `POST /echo` | Returns the request body |
| `POST /v1/chat/completions` | OpenAI-style fake LLM, supports `stream: true` |

## Responsible use

Only test systems you own or have permission to test. Load testing someone else's service
without permission can be illegal and is treated as an attack.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Licensed under the [MIT License](LICENSE).
