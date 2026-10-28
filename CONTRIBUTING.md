# Contributing to LoadPilot

Thanks for helping! Bug reports, docs fixes and code are all welcome.

## Development setup

Backend (Python 3.11+, [uv](https://docs.astral.sh/uv/)):

```bash
cd backend
uv sync                      # creates .venv with dev dependencies
uv run pytest                # tests
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy loadpilot        # type check (strict)
```

Frontend (Node.js 22+, [pnpm](https://pnpm.io/)):

```bash
cd frontend
pnpm install
pnpm dev                     # Vite on :5173, proxies /api, /ws and /demo to :8089
pnpm typecheck
pnpm test                    # unit tests (Vitest)
pnpm build                   # outputs to backend/loadpilot/static
pnpm exec playwright install chromium   # once
pnpm test:e2e                # browser tests against the built UI (starts the server itself)
```

For UI work, `./start.sh --dev` from the repo root starts the API server and the Vite dev
server with hot reload (http://localhost:5173), and stops both on Ctrl+C.

**macOS + Python 3.13+:** if `uv run loadpilot` fails with `No module named 'loadpilot'`
inside `~/Documents` or another synced folder, macOS has marked the venv's `.pth` files as
hidden and Python skips them. Either run `chflags -R nohidden .venv`, or use
`uv run python -m loadpilot ...` from `backend/`, which doesn't depend on those files.

## Project layout

```
backend/loadpilot/
  config/       test-plan models (pydantic) and duration parsing
  engine/       load scheduler (open + closed models) and HTTP transport
  metrics/      histogram, per-second collector, run aggregator
  demo_server/  mock target for trying things out and for tests
  controller/   run manager: one active run, live subscribers, controls
  api/          FastAPI app: REST, WebSocket stream, serves the built UI
  cli.py        `loadpilot` command
frontend/src/
  pages/        New test form, live run view
  components/   charts (uPlot), controls, tables
  lib/          pure helpers (form → plan, formatting, stream reducer), unit tested
```

UI direction (colours, type, density) is in [DESIGN.md](DESIGN.md).

The engine emits one **tick** per second: a self-contained, mergeable snapshot of
counters and histograms. Everything downstream (CLI, UI, distributed workers) consumes ticks.

## Pull requests

- Keep PRs focused; open an issue first for larger changes.
- Add or update tests. Timing-sensitive tests should use generous tolerances.
- All checks above must pass.
- Update `CHANGELOG.md` under "Unreleased".

By contributing you agree your work is licensed under the MIT License and that you
follow our [Code of Conduct](CODE_OF_CONDUCT.md).
