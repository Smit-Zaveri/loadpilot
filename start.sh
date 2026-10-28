#!/usr/bin/env bash
# Start LoadPilot: installs what's missing, builds the UI if needed, runs the server.
# Usage: ./start.sh [--dev] [--port N] [--no-open] [--rebuild]   (see --help)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
STATIC_INDEX="$BACKEND/loadpilot/static/index.html"

PORT=8089
DEV_PORT=5173
DEV=0
OPEN=1
REBUILD=0

usage() {
  cat <<EOF
Start LoadPilot.

  ./start.sh              Install dependencies if needed, build the UI if it changed,
                          start the server on http://127.0.0.1:$PORT and open the browser.
  ./start.sh --dev        Development mode: API server plus the Vite dev server with
                          hot reload on http://localhost:$DEV_PORT.

Options:
  --port N     Port for the LoadPilot server (default $PORT)
  --no-open    Don't open a browser
  --rebuild    Rebuild the UI even if it looks up to date
  -h, --help   Show this help

Press Ctrl+C to stop.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dev) DEV=1 ;;
    --no-open) OPEN=0 ;;
    --rebuild) REBUILD=1 ;;
    --port)
      [[ $# -ge 2 && "$2" =~ ^[0-9]+$ ]] || { echo "Error: --port needs a number" >&2; exit 2; }
      PORT="$2"
      shift
      ;;
    -h | --help) usage; exit 0 ;;
    *) echo "Error: unknown option '$1' (see --help)" >&2; exit 2 ;;
  esac
  shift
done

step() { printf '\033[1m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[31mError:\033[0m %s\n' "$*" >&2; exit 1; }

# ---- prerequisites -------------------------------------------------------

command -v uv >/dev/null 2>&1 ||
  fail "uv is not installed. Install it: https://docs.astral.sh/uv/getting-started/installation/"
command -v node >/dev/null 2>&1 || fail "Node.js is not installed (version 22 or newer): https://nodejs.org/"
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[[ "$NODE_MAJOR" -ge 22 ]] || fail "Node.js 22 or newer is required (found $(node --version))."
command -v pnpm >/dev/null 2>&1 ||
  fail "pnpm is not installed. Install it with 'corepack enable pnpm' or see https://pnpm.io/installation"

port_in_use() {
  command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1
}
port_in_use "$PORT" && fail "port $PORT is already in use. Stop that process or use --port."
if [[ $DEV -eq 1 ]] && port_in_use "$DEV_PORT"; then
  fail "port $DEV_PORT (Vite dev server) is already in use."
fi

# ---- dependencies --------------------------------------------------------

step "Python dependencies"
(cd "$BACKEND" && uv sync --quiet)

# Our own stamp: pnpm doesn't touch its files when nothing changed, so they can't tell us.
INSTALL_STAMP="$FRONTEND/node_modules/.loadpilot-installed"
if [[ ! -f "$INSTALL_STAMP" || "$FRONTEND/pnpm-lock.yaml" -nt "$INSTALL_STAMP" || "$FRONTEND/package.json" -nt "$INSTALL_STAMP" ]]; then
  step "Installing frontend dependencies"
  (cd "$FRONTEND" && pnpm install --frozen-lockfile)
  touch "$INSTALL_STAMP"
else
  step "Frontend dependencies up to date"
fi

# ---- UI build (production mode only) -------------------------------------

ui_is_stale() {
  [[ ! -f "$STATIC_INDEX" ]] && return 0
  [[ -n "$(find "$FRONTEND/src" "$FRONTEND/index.html" "$FRONTEND/package.json" \
    "$FRONTEND/vite.config.ts" "$FRONTEND/pnpm-lock.yaml" -newer "$STATIC_INDEX" -print -quit)" ]]
}

if [[ $DEV -eq 0 ]]; then
  if [[ $REBUILD -eq 1 ]] || ui_is_stale; then
    step "Building the UI"
    (cd "$FRONTEND" && pnpm build)
  else
    step "UI build up to date"
  fi
fi

# ---- run -----------------------------------------------------------------

# `python -m` from backend/ imports the package directly, so it works even when macOS has
# hidden the venv's .pth files (which breaks the `loadpilot` command in synced folders).
run_server() {
  (cd "$BACKEND" && exec uv run --no-sync python -m loadpilot ui --port "$PORT" "$@")
}

if [[ $DEV -eq 0 ]]; then
  if [[ $OPEN -eq 1 ]]; then run_server --open; else run_server; fi
  exit 0
fi

# Dev mode runs two servers. Both run in the background so the trap fires immediately on
# Ctrl+C or kill (bash defers traps while a foreground child runs), then stops both trees.
kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$child"; done
  kill "$pid" 2>/dev/null || true
}
PIDS=()
cleanup() {
  trap - EXIT INT TERM
  # ${PIDS[@]+...} keeps bash 3.2 (macOS default) from failing on an empty array under set -u.
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do kill_tree "$pid"; done
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

step "Starting the API server on port $PORT"
run_server &
PIDS+=($!)

for _ in $(seq 1 100); do
  curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break
  kill -0 "${PIDS[0]}" 2>/dev/null || fail "the API server exited during startup."
  sleep 0.1
done

step "Starting the Vite dev server on http://localhost:$DEV_PORT (hot reload)"
VITE_ARGS=(--port "$DEV_PORT" --strictPort)
[[ $OPEN -eq 1 ]] && VITE_ARGS+=(--open)
(cd "$FRONTEND" && LOADPILOT_PORT="$PORT" exec ./node_modules/.bin/vite "${VITE_ARGS[@]}") &
PIDS+=($!)

# Exit (and clean up) as soon as either server stops.
while kill -0 "${PIDS[0]}" 2>/dev/null && kill -0 "${PIDS[1]}" 2>/dev/null; do
  sleep 1
done
fail "a server stopped unexpectedly; shutting down the other one."
