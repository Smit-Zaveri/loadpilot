# Contributing to LoadPilot

Thanks for helping! Bug reports, docs fixes and code are all welcome.

## Development setup

```bash
cd backend
uv sync                      # creates .venv with dev dependencies
uv run pytest                # tests
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy loadpilot        # type check (strict)
```

**macOS + Python 3.13+:** if `uv run loadpilot` fails with `No module named 'loadpilot'`
inside `~/Documents` or another synced folder, macOS has marked the venv's `.pth` files as
hidden and Python skips them. Fix it with `chflags -R nohidden .venv`.

## Project layout

```
backend/loadpilot/
  config/       test-plan models (pydantic) and duration parsing
  engine/       load scheduler (open + closed models) and HTTP transport
  metrics/      histogram, per-second collector, run aggregator
  demo_server/  mock target for trying things out and for tests
  cli.py        `loadpilot` command
```

The engine emits one **tick** per second: a self-contained, mergeable snapshot of
counters and histograms. Everything downstream (CLI, UI, distributed workers) consumes ticks.

## Pull requests

- Keep PRs focused; open an issue first for larger changes.
- Add or update tests. Timing-sensitive tests should use generous tolerances.
- All checks above must pass.
- Update `CHANGELOG.md` under "Unreleased".

By contributing you agree your work is licensed under the MIT License and that you
follow our [Code of Conduct](CODE_OF_CONDUCT.md).
