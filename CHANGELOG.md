# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Web UI (`loadpilot ui`): new-test form with validation, live run view with throughput,
  latency percentile, failure and concurrency charts, per-step table, status codes and errors.
- Live load control from the browser (slider), pause/resume/stop/abort, with chart markers.
- Load-generator overload and dropped-request warnings in the UI.
- Dark (default) and light themes, keyboard accessible, works on phones.
- REST + WebSocket API (`/api/runs`, `/ws/runs/{id}`), one active run at a time.
- Security defaults: binds to 127.0.0.1, Host-header check (DNS rebinding), WebSocket
  Origin check, JSON-only POSTs (CSRF), secret-looking headers masked in API responses.
- Demo target mounted at `/demo` inside the UI server.
- `python -m loadpilot` entry point.

### Changed
- Default HTTP client is now aiohttp (httpx collapsed under concurrency: 269 vs 14,138 RPS
  at 50 connections).
- `uvicorn[standard]` for WebSocket support and uvloop.

### Fixed
- Query strings in target URLs were dropped by the HTTP client.

### Added (engine, CLI)
- Load engine with closed (virtual users) and open (arrival rate) models, linear-ramp stages,
  live `set_load`, pause/resume, graceful stop and abort.
- Coordinated-omission-safe latency for open-model tests, plus separate service time.
- Mergeable per-second metric ticks with log-bucketed histograms (~1% error).
- Load-generator health: event-loop lag measurement and warnings.
- `loadpilot run` CLI (flags or YAML), live per-second output, summary, JSON export.
- `loadpilot demo-server` mock target: latency, errors, 429 rate limiting, fake streaming LLM.
