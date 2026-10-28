# LoadPilot — Detailed Plan

> Working name; easy to rename before the first release.
> An open-source (MIT), self-hosted load and performance testing tool with a live web UI.
> Works with any HTTP API and adds metrics specific to LLM APIs.

---

## 1. Vision

Run `docker run -p 8089:8089 loadpilot` or `pip install loadpilot && loadpilot ui`,
open `http://localhost:8089`, paste a URL, move a slider, and watch latency,
throughput, and errors live. Load can be raised or lowered while the test runs.
The same test file then runs in CI and fails the build if p95 gets worse.

### Who it's for
| User | Need |
|------|------|
| Backend dev | "How many RPS can my endpoint handle before p99 explodes?" |
| LLM app dev | "What's the time to first token and tokens/sec of my model or gateway under 50 concurrent users? When do I hit 429s?" |
| DevOps / SRE | Repeatable tests in CI with pass/fail limits; compare before and after a deploy |
| OSS contributor | Clean code that's easy to extend (new protocols, exporters, charts) |

### Not in scope for v1
- A public hosted service that sends load to any URL (abuse risk). Self-hosted only.
- Protocols other than HTTP/1.1 and HTTP/2 (gRPC, WebSocket and GraphQL subscriptions come later).
- Browser or real-user testing (Playwright).
- Running JavaScript or Python inside scenarios. v1 scenarios are declarative YAML.

---

## 2. Feature list (v1 scope, everything you selected)

### 2.1 Test builder
- Target: method, URL, headers, query, body (JSON, form, raw), timeout, follow redirects, TLS verify toggle.
- **Load model** (both are needed; see §4.1):
  - *Closed model*: N virtual users (VUs) loop the scenario, with optional think time.
  - *Open model*: target arrival rate (requests or iterations per second), independent of response time.
- **Stages / ramp**: list of `{duration, target}` steps, e.g. 0 to 50 VUs over 30s, hold 2m, down to 0 over 10s.
- Duration or iteration-count limit, warm-up period (left out of the stats).
- Presets: Smoke, Load, Stress, Spike, Soak. Each is a ready-made stages template.
- "Import from cURL" (paste a curl command and the form fills in). Export a test as YAML.

### 2.2 Live dashboard
- Updated every second over a WebSocket.
- Big-number tiles: current RPS, p50, p95, p99, error %, active VUs, total requests, data in/out.
- Charts (time series):
  - Throughput (RPS) against the target RPS
  - Latency percentiles (p50, p90, p95, p99, max)
  - Error rate, and status codes stacked (2xx/3xx/4xx/5xx/429/network errors)
  - Active VUs / in-flight requests
  - Latency histogram (distribution) for the whole run so far
  - LLM tab: time to first token, inter-token latency, output tokens/sec, tokens per request, estimated cost
- Per-step table for scenarios: count, error %, p50, p95, p99, avg size.
- Error log panel: grouped by error type, with sample responses (truncated).
- **Load-generator health** indicator: event-loop lag, CPU of the generator. A warning appears when the
  generator itself is the bottleneck, so results aren't trusted when they shouldn't be.

### 2.3 Live load control
- While running: slider to change VUs or target RPS, applied within about 1 second.
- Pause / Resume / Stop (graceful: let in-flight requests finish) / Abort (cancel immediately).
- Manual changes show as markers on the charts ("RPS changed 100 → 200 at 01:32").
- Safety cap: global max RPS / max VUs in settings, so nobody can accidentally overload a target.

### 2.4 Multi-step scenarios
```yaml
name: login-and-chat
variables:
  base: https://api.example.com
data:
  users: { csv: ./users.csv, mode: sequential }   # sequential | random | unique
steps:
  - name: login
    request:
      method: POST
      url: "{{ base }}/login"
      json: { email: "{{ users.email }}", password: "{{ users.password }}" }
    extract:
      token: { jsonpath: "$.access_token" }
    assert:
      - status: 200
  - think: 1s..3s
  - name: chat
    weight: 1
    request:
      method: POST
      url: "{{ base }}/v1/chat/completions"
      headers: { Authorization: "Bearer {{ token }}" }
      json: { model: gpt-4o-mini, stream: true, messages: [{ role: user, content: "Hi" }] }
    llm: { format: openai }          # turns on TTFT / token metrics
    assert:
      - status: 200
      - latency_ms: "< 5000"
```
- Templating: `{{ var }}` plus built-ins: `{{ uuid() }}`, `{{ random_int(1,100) }}`, `{{ now() }}`, `{{ env.API_KEY }}`.
- Extractors: JSONPath, regex, header, cookie (a cookie jar per VU).
- Assertions: status, latency, body contains, JSONPath equals. A failure is counted separately from transport errors.
- Data feeders: CSV / JSON files.
- UI: a visual step editor (add/reorder steps) **and** a YAML editor (Monaco). The two stay in sync.

### 2.5 LLM extras
- Streaming support: Server-Sent Events (OpenAI style `data: ...`) and newline-delimited JSON.
- Metrics: TTFT, inter-token latency (ITL), output tokens/sec per request and overall, prompt and completion tokens
  (from the `usage` field, or estimated from characters/4 if missing), total time.
- Formats: `openai` (also covers vLLM, Ollama-compatible, LiteLLM, OpenRouter, Groq…), `anthropic`, `generic` (regex / JSONPath setup).
- Rate-limit view: share of 429 responses, observed `Retry-After` and `x-ratelimit-*` headers on a chart.
- Optional cost estimate: user enters $ per 1M input/output tokens.
- Prompt variety: choose prompts from a list or file, so caching doesn't distort results.

### 2.6 History and compare
- Every run is saved: config snapshot, per-second time series, final summary, merged latency histogram, error samples.
- History page: search, filter, tags, notes, delete, re-run with the same settings.
- Compare: choose 2 or more runs, overlay their charts, and show a summary table with deltas (green/red), e.g. "p95 +18%".
- Mark a run as **baseline**. CI can compare against it.

### 2.7 Export and CI mode
- Export: JSON (full data), CSV (time series and per-request summary), **self-contained HTML report** (one file with charts, shareable), JUnit XML (for CI test views).
- CLI:
  ```bash
  loadpilot run test.yaml --vus 50 --duration 2m \
     --threshold "http.p95<300ms" --threshold "http.error_rate<1%" \
     --out report.html --out results.json
  ```
  The exit code is non-zero when a threshold fails. Thresholds can also be in the YAML.
- Headless (no UI needed), with a plain progress bar in the terminal.
- Official GitHub Action `loadpilot/action@v1` plus an example workflow that comments the summary on PRs.

### 2.8 Distributed workers
- One **controller** (the UI and API) and N **workers**:
  ```bash
  loadpilot controller                      # runs UI + coordinates
  loadpilot worker --controller ws://host:8089 --token XXX
  ```
- The controller splits the target load across workers (by weight or evenly), sends the test plan, and starts everyone together.
- Workers send per-second histogram snapshots. The controller merges them (HDR histograms can be merged exactly).
- Workers page in the UI: connected workers, CPU, event-loop lag, current RPS, status.
- When a worker fails: heartbeat timeout, the run is marked degraded, and its share is optionally handed to the others.
- **Local multi-core uses the same design**: `--processes auto` starts local worker processes. Python's GIL limits one process to one CPU core, so this matters even on one machine.

### 2.9 Built-in demo target
Because there's no longer a rate-limiter project to test against, LoadPilot includes a small **mock server**
(`loadpilot demo-server`, also a toggle in the UI) with adjustable endpoints:
- `/fast`, `/slow?ms=200`, `/random-latency`, `/flaky?error_rate=0.1`
- `/rate-limited` (token bucket, returns 429 + `Retry-After`)
- `/v1/chat/completions` that streams fake tokens at a configurable speed
New users can try every feature in 10 seconds without hitting a real service.

---

## 3. Architecture

```
                ┌──────────────────────── Browser (React UI) ────────────────────────┐
                │ Builder · Live Dashboard · Scenarios · History · Compare · Workers │
                └───────────────┬───────────────────────────────▲────────────────────┘
                     REST (JSON)│                   WebSocket   │ 1 s metric ticks, events
                ┌───────────────▼───────────────────────────────┴────────────────────┐
                │                   Controller (FastAPI, uvicorn)                    │
                │  API · Run manager · Metrics aggregator · Threshold eval · Storage │
                └───────┬──────────────────────────┬───────────────────────┬─────────┘
                        │ control/metrics protocol │                       │ SQLAlchemy
               ┌────────▼──────┐          ┌────────▼──────┐          ┌─────▼─────┐
               │ Local worker  │   ...    │ Remote worker │          │  SQLite   │
               │ (process #n)  │          │ (other host)  │          │ (runs DB) │
               │ asyncio engine│          │ asyncio engine│          └───────────┘
               └───────┬───────┘          └───────┬───────┘
                       └──────── HTTP load ───────┴──────────► Target system
```

- **The engine runs only in workers.** The controller never sends load itself, so the UI stays responsive.
- Local mode starts worker *processes* that talk to the controller over a local channel (multiprocessing pipe
  or localhost WebSocket). Remote workers use the same messages over WebSocket. One code path for both.
- The **CLI** (`loadpilot run`) starts a controller in-process with no web server, so CI results match UI results exactly.

### 3.1 Controller ↔ worker messages (JSON over WebSocket, versioned)
| Direction | Message | Payload |
|-----------|---------|---------|
| W→C | `hello` | worker id, version, cores, token |
| C→W | `prepare` | test plan, share of load, data-feeder partition |
| C→W | `start` | start timestamp (synced) |
| C→W | `set_load` | new target VUs / RPS (live control) |
| C→W | `pause` / `resume` / `stop` / `abort` | — |
| W→C | `tick` | second index, encoded HDR histograms per metric/step, counters, errors sample, health |
| W→C | `heartbeat` | every 2 s |
| W→C | `done` | final counters |

Clock: ticks are numbered by "seconds since start" on the worker, so clock skew between machines doesn't matter.

---

## 4. Load engine (the hard part)

### 4.1 Two load models
- **Closed (VUs)**: each VU is an asyncio task running `while running: run_scenario(); think()`.
  Throughput = VUs / (latency + think). If the target slows down, load also drops. This is realistic for user sessions.
- **Open (arrival rate)**: a scheduler starts iterations at fixed planned times (an interval of 1/rate, optionally
  Poisson), whether or not earlier ones have finished. This is needed for honest latency numbers (see 4.2).
  There's a cap on in-flight requests; anything over the cap is counted as **dropped iterations** and shown in the UI.

### 4.2 Accuracy rules
- **Coordinated omission**: in open mode, latency is measured from the *planned* start time, not the actual send time.
  Otherwise a stalled server looks faster than it is. Both are recorded: "service time" and "response time".
- Use `time.perf_counter_ns()` for all timing.
- Warm-up seconds are left out of the summary.
- **Generator health**: measure event-loop lag every 100 ms. Above about 50 ms, warn "results may be limited by the load generator".
- Connection pooling per worker with configurable keep-alive. Option for a "new connection per request" mode.
- DNS / connect / TLS / TTFB / download timings broken out where the HTTP client exposes them.

### 4.3 HTTP client choice (decided in Phase 1)
- **aiohttp is the default transport.** Benchmark on a local `/fast` endpoint:

  | Concurrency | httpx | aiohttp |
  |---|---|---|
  | 1 | 1,962 RPS | 5,524 RPS |
  | 10 | 2,286 RPS | 13,170 RPS |
  | 50 | **269 RPS** | **14,138 RPS** |

  httpx's connection pool falls over under concurrency, so it can't be the engine's client.
- The client sits behind the `Transport` interface. An optional httpx transport may come back
  later for HTTP/2 only. Use `uvloop` on Linux/macOS when it's installed (later).
- Measured: about 14k RPS from one process at 50 VUs against the demo server. Scale up with more processes or workers.

### 4.4 Metrics pipeline
- Each worker keeps, per second and per step: HDR histograms (`hdrhistogram` package) for latency, TTFT, ITL; counters
  (requests, by status, errors by type, bytes, tokens, dropped iterations, assertion failures).
- At each second: encode the histograms (base64), send a `tick`, reset.
- Controller: merges ticks from all workers for that second, then updates (a) the live per-second series,
  (b) a running whole-run histogram, (c) threshold checks. Then it sends a compact tick to the UI.
- Late ticks (up to 3 s) are still merged; a second is shown once every worker has reported or after a timeout.
- Memory stays flat regardless of request count. Individual requests are never stored (only error samples, capped at about 100 per type).

---

## 5. Data model (SQLite via SQLAlchemy / SQLModel, Alembic migrations)

| Table | Key columns |
|-------|-------------|
| `tests` | id, name, yaml, created_at, updated_at (saved test definitions) |
| `runs` | id, test_id?, name, status, config_snapshot (JSON), started_at, ended_at, tags, notes, is_baseline, thresholds_result |
| `run_series` | run_id, second, step, metrics (JSON: rps, p50…p99, errors, status counts, tokens…) |
| `run_histograms` | run_id, step, metric, encoded_hdr (final merged) |
| `run_errors` | run_id, step, error_type, count, samples (JSON) |
| `settings` | key, value (safety caps, default headers, cost per token…) |

DB location: `~/.loadpilot/loadpilot.db` (configurable; mounted as a volume in Docker).

---

## 6. REST + WebSocket API (controller)

```
GET    /api/health
GET    /api/tests                 POST /api/tests        GET/PUT/DELETE /api/tests/{id}
POST   /api/tests/validate        (YAML → errors with line numbers)
POST   /api/tests/import-curl
POST   /api/runs                  (start run from test id or inline config)
GET    /api/runs?tag=&q=&page=    GET /api/runs/{id}     DELETE /api/runs/{id}
POST   /api/runs/{id}/control     {action: pause|resume|stop|abort|set_load, value}
GET    /api/runs/{id}/series      GET /api/runs/{id}/summary
GET    /api/runs/{id}/export?format=json|csv|html|junit
GET    /api/compare?ids=1,2,3
GET    /api/workers
GET/PUT /api/settings
WS     /ws/runs/{id}              (live ticks + events)
WS     /ws/workers                (worker connections)
```
FastAPI generates the OpenAPI spec automatically. The TypeScript client for the UI is generated from it (`openapi-typescript`), so types never drift.

---

## 7. UI

**Stack**: React 18 + Vite + TypeScript, Tailwind + shadcn/ui (accessible components), TanStack Query (REST),
native WebSocket hook, **uPlot** for live time-series charts (handles high-frequency updates far better than Recharts),
Monaco editor for YAML, Zustand for live-run state. Dark/light theme. The built UI ships *inside* the Python package as static files.

### Pages
1. **Home / New test**: quick form (URL + method + VUs/RPS + duration + "Start"). A "Try demo target" button.
   An advanced section opens headers, body, stages, thresholds, LLM options.
2. **Live run**: header with status, elapsed / remaining time, Pause/Stop/Abort, load slider (VUs or RPS).
   Tiles row → charts grid → per-step table → errors panel. Tabs: Overview · Latency · Errors · LLM · Workers.
3. **Scenarios**: list plus editor (visual steps ↔ YAML), "Validate", "Dry run (1 iteration)" showing each request/response.
4. **History**: table of runs (name, date, duration, peak RPS, p95, error %, pass/fail badge, tags). Multi-select → Compare.
5. **Run report**: the same layout as Live, read-only, plus export buttons.
6. **Compare**: overlaid charts, delta table, "set as baseline".
7. **Workers**: connected workers, health, join command with a copy button (`loadpilot worker --controller … --token …`).
8. **Settings**: safety caps, allowed target hosts (optional allowlist), default headers, token prices, data retention.

### UX principles
- A first test takes under 30 seconds and a single field (URL).
- Every number has a tooltip explaining it ("p95: 95% of requests were faster than this").
- Charts keep a fixed time window with a "follow live" toggle. Hover syncs across charts.
- Usable with a keyboard, color-blind-safe palette, status never shown by color alone.

---

## 8. Security and responsible use
- Binds to `127.0.0.1` by default. Binding to `0.0.0.0` requires `--auth-token` (or prints a big warning).
- Workers authenticate with a shared token. Use WSS when the controller runs behind TLS.
- Secrets: `{{ env.X }}` values and headers like `Authorization` are **masked** in the UI, saved run snapshots, and exports.
- Global safety caps (max RPS / VUs / duration) and an optional host allowlist.
- README section "Only test systems you own or have permission to test."
- No telemetry. No analytics, ever (state it in the README).

---

## 9. Repository layout (monorepo)

```
loadpilot/
├── backend/
│   ├── pyproject.toml              # package "loadpilot", entry point `loadpilot`
│   ├── loadpilot/
│   │   ├── cli.py                  # typer: ui, run, worker, controller, demo-server
│   │   ├── config/                 # pydantic models for test YAML, validation, templating
│   │   ├── engine/                 # scheduler (open/closed), vu, transport, scenario runner, extractors, assertions
│   │   ├── llm/                    # SSE parsing, token metrics, format adapters
│   │   ├── metrics/                # hdr wrappers, tick encode/merge, aggregator, thresholds
│   │   ├── controller/             # run manager, worker registry, protocol
│   │   ├── api/                    # FastAPI routers + websocket
│   │   ├── storage/                # SQLAlchemy models, repo, alembic
│   │   ├── export/                 # json, csv, junit, html (jinja2 + inlined chart JS)
│   │   ├── demo_server/            # mock target
│   │   └── static/                 # built UI (copied in at build time, git-ignored)
│   └── tests/
├── frontend/
│   ├── package.json
│   └── src/ (pages, components, charts, api client, hooks, stores)
├── docs/                           # mkdocs-material site: quickstart, YAML reference, CI guide, distributed guide
├── examples/                       # sample YAML tests (REST, scenario, OpenAI, Ollama)
├── action/                         # GitHub Action
├── docker/Dockerfile               # multi-stage: build UI → python slim image
├── .github/workflows/              # lint, test, build, release (PyPI + GHCR)
├── LICENSE (MIT) · README.md · CONTRIBUTING.md · CODE_OF_CONDUCT.md · SECURITY.md · CHANGELOG.md
└── .github/ISSUE_TEMPLATE/, PULL_REQUEST_TEMPLATE.md
```

Tooling: `uv` for Python, `ruff` + `mypy`, `pytest` + `pytest-asyncio`; `pnpm`, `eslint`, `prettier`, `vitest`, Playwright for UI e2e.
Python ≥ 3.11. Versioning: SemVer, release-please for changelogs.

---

## 10. Testing the tool itself
- **Unit**: templating, extractors, assertions, YAML validation, HDR merge, threshold parser, SSE parser.
- **Engine accuracy**: run against the demo server with known latency (e.g. 100 ms fixed). Check that p50 ≈ 100 ms,
  achieved RPS ≈ target ±2%, and that coordinated-omission correction shows up when the server stalls.
- **Live control**: change RPS mid-run; check the achieved rate follows within 2 s.
- **Distributed**: start 1 controller + 3 workers in pytest; total RPS = target; kill one worker → run marked degraded.
- **API**: FastAPI TestClient. **UI**: vitest components + Playwright smoke (start demo run, see charts move, stop, export).
- **Performance benchmark** in CI (nightly): max RPS per core, so slowdowns get caught.

---

## 11. Milestones

Progress: ✅ Phase 0 · ✅ Phase 1 · ✅ Phase 2 · 🟡 Phase 3 (live slider, chart markers and
generator-health warning done; safety caps remaining) · ⏭ Phase 4 next

Decisions made while building Phase 2 (differ from §7):
- **Plain CSS with design tokens** instead of Tailwind + shadcn/ui. The instrument-panel look
  (see `DESIGN.md`) needs few components, and tokens keep both themes exact.
- **fetch + small hooks** instead of TanStack Query; **hand-written API types** in `src/api.ts`.
  Generate them from OpenAPI once the API grows (Phase 4).
- **One active run at a time** per server, so the generator's CPU isn't shared between runs.
- Runs live in memory until restart; SQLite storage comes in Phase 4.

| Phase | Deliverable | Done when |
|-------|-------------|-----------|
| **0. Setup** | Monorepo, tooling, CI, LICENSE, README skeleton, demo server | `pytest` and `pnpm build` green in CI |
| **1. Engine core** | Single-process asyncio engine, closed + open models, stages, HDR metrics, CLI `run` with terminal summary | Accuracy tests pass against the demo server |
| **2. Controller + live UI** | FastAPI, WebSocket ticks, Home builder, Live dashboard with charts, pause/stop | Start a test from the browser, watch it live |
| **3. Live control + safety** | `set_load`, markers, caps, generator-health warning | Slider changes RPS within about 1 s |
| **4. Storage, history, compare** | SQLite, run reports, compare view, baseline | Re-open and compare past runs |
| **5. Scenarios** | YAML schema, templating, extractors, assertions, feeders, visual + Monaco editor, dry run | login → chat example works |
| **6. LLM extras** | SSE streaming, TTFT/ITL/tokens/sec, 429 view, cost | Demo LLM endpoint shows token metrics |
| **7. Export + CI** | JSON/CSV/HTML/JUnit, thresholds, exit codes, GitHub Action | Example workflow fails on a slow PR |
| **8. Multi-process + distributed** | Worker protocol, local `--processes`, remote workers, Workers page | 3 workers combine their load correctly |
| **9. Release v0.1** | Docker image, PyPI, docs site, examples, demo GIF in README | `docker run` → working UI in under 1 min |

The order is chosen so each phase gives something usable. The worker protocol is designed in phase 1 (the engine
already reports through `tick` messages) so phase 8 doesn't need a rewrite.

---

## 12. Risks
| Risk | Mitigation |
|------|------------|
| Python throughput limits | Multi-process by default, aiohttp/uvloop option, publish honest benchmarks |
| Wrong results without anyone noticing (coordinated omission, saturated generator) | Planned-time measurement, event-loop lag warning, accuracy tests in CI |
| Scope is large | Strict phase order; distributed mode last; each phase can be released on its own |
| Misuse as an attack tool | Self-hosted only, localhost default, caps, allowlist, clear policy |
| UI lag with many series | uPlot, 1 s batching, cap visible window, downsample history |
