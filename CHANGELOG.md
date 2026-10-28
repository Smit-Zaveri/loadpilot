# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Load engine with closed (virtual users) and open (arrival rate) models, linear-ramp stages,
  live `set_load`, pause/resume, graceful stop and abort.
- Coordinated-omission-safe latency for open-model tests, plus separate service time.
- Mergeable per-second metric ticks with log-bucketed histograms (~1% error).
- Load-generator health: event-loop lag measurement and warnings.
- `loadpilot run` CLI (flags or YAML), live per-second output, summary, JSON export.
- `loadpilot demo-server` mock target: latency, errors, 429 rate limiting, fake streaming LLM.
