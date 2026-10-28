from __future__ import annotations

import asyncio
import json
import signal
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import TestPlan
from .engine import Engine, RunState
from .metrics import RunAggregator

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="LoadPilot: load and performance testing for HTTP and LLM APIs.",
)
console = Console()
err_console = Console(stderr=True)

_LAG_WARNING_MS = 50.0


@app.command()
def run(
    plan_file: Annotated[
        Path | None,
        typer.Argument(exists=True, dir_okay=False, help="YAML test file."),
    ] = None,
    url: Annotated[str | None, typer.Option("--url", "-u", help="Target URL (no file).")] = None,
    method: Annotated[str, typer.Option("--method", "-X")] = "GET",
    header: Annotated[
        list[str] | None, typer.Option("--header", "-H", help="'Name: value', repeatable.")
    ] = None,
    body: Annotated[
        str | None, typer.Option("--body", "-d", help="Request body; JSON is detected.")
    ] = None,
    vus: Annotated[int | None, typer.Option(help="Virtual users (closed model).")] = None,
    rate: Annotated[float | None, typer.Option(help="Iterations per second (open model).")] = None,
    duration: Annotated[str | None, typer.Option(help="e.g. 30s, 2m.")] = None,
    warmup: Annotated[str | None, typer.Option(help="Leave this long out of the summary.")] = None,
    insecure: Annotated[bool, typer.Option(help="Skip TLS certificate checks.")] = False,
    out: Annotated[Path | None, typer.Option(help="Write full results as JSON.")] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="No per-second output.")] = False,
) -> None:
    """Run a load test from a YAML file or straight from flags."""
    plan = _build_plan(
        plan_file, url, method, header or [], body, vus, rate, duration, warmup, insecure
    )
    mode = "virtual users" if plan.load.mode == "vus" else "iterations/s"
    console.print(
        f"[bold]LoadPilot[/] {__version__} · [cyan]{plan.name}[/] · "
        f"{len(plan.steps)} step(s) · {plan.load.total_duration:g}s · target in {mode}"
    )
    console.print("[dim]Ctrl+C stops gracefully, press again to abort.[/]")

    aggregator, state = asyncio.run(_execute(plan, quiet))
    summary = aggregator.summary()
    _print_summary(plan, summary)

    if out is not None:
        out.write_text(
            json.dumps(
                {
                    "loadpilot_version": __version__,
                    "state": state.value,
                    "plan": plan.model_dump(mode="json", by_alias=True),
                    "summary": summary,
                    "series": aggregator.series,
                    "events": aggregator.events,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        console.print(f"Results written to [bold]{out}[/]")
    if state is RunState.ABORTED:
        raise typer.Exit(130)


@app.command()
def ui(
    host: Annotated[
        str, typer.Option(help="Interface to bind. Keep 127.0.0.1 unless you need remote access.")
    ] = "127.0.0.1",
    port: int = 8089,
    open_browser: Annotated[bool, typer.Option("--open", help="Open the UI in a browser.")] = False,
    demo: Annotated[bool, typer.Option(help="Serve the demo target at /demo.")] = True,
) -> None:
    """Start the web UI and API server."""
    import uvicorn

    from .api import LOOPBACK_HOSTS, create_app

    local = host in LOOPBACK_HOSTS
    if not local:
        err_console.print(
            f"[bold yellow]Warning:[/] binding to {host}. Anyone who can reach this address can "
            "start load tests from this machine. LoadPilot has no login yet; only do this on a "
            "trusted network."
        )
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"
    console.print(f"[bold]LoadPilot[/] {__version__} · UI on [cyan]{url}[/]  (Ctrl+C to quit)")
    if demo:
        console.print(f"[dim]Demo target: {url}/demo/[/]")
    if open_browser:
        import threading
        import webbrowser

        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(
        create_app(demo=demo, allowed_hosts=None if local else ["*"]),
        host=host,
        port=port,
        log_level="warning",
    )


@app.command("demo-server")
def demo_server(
    host: str = "127.0.0.1",
    port: int = 8090,
    rate_limit_capacity: int = typer.Option(20, help="Burst size for /rate-limited."),
    rate_limit_per_second: float = typer.Option(10.0, help="Refill rate for /rate-limited."),
) -> None:
    """Start the built-in mock target (latency, errors, 429s, fake LLM streaming)."""
    import uvicorn

    from .demo_server import create_app

    console.print(f"[bold]LoadPilot demo target[/] on http://{host}:{port}  (endpoints: GET /)")
    uvicorn.run(
        create_app(
            rate_limit_capacity=rate_limit_capacity, rate_limit_per_second=rate_limit_per_second
        ),
        host=host,
        port=port,
        log_level="warning",
    )


@app.command()
def version() -> None:
    """Print the version."""
    console.print(__version__)


# ---- helpers ------------------------------------------------------------


def _build_plan(
    plan_file: Path | None,
    url: str | None,
    method: str,
    headers: list[str],
    body: str | None,
    vus: int | None,
    rate: float | None,
    duration: str | None,
    warmup: str | None,
    insecure: bool,
) -> TestPlan:
    if vus is not None and rate is not None:
        _fail("use either --vus or --rate, not both")

    if plan_file is not None:
        if url is not None:
            _fail("--url cannot be combined with a test file")
        try:
            data = yaml.safe_load(plan_file.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            _fail(f"invalid YAML in {plan_file}: {e}")
        if not isinstance(data, dict):
            _fail(f"{plan_file} must contain a YAML mapping")
    elif url is not None:
        data = {
            "name": f"{method.upper()} {url}",
            "request": _request_from_flags(url, method, headers, body),
        }
        data["load"] = {}
    else:
        _fail("give a test file or --url")

    load = dict(data.get("load") or {})
    if vus is not None or rate is not None:
        for key in ("vus", "rate", "mode", "stages", "start"):
            load.pop(key, None)
        load["vus" if vus is not None else "rate"] = vus if vus is not None else rate
        load.setdefault("duration", "30s")
    elif plan_file is None:
        load.setdefault("vus", 1)
    if duration is not None:
        if load.get("stages"):
            _fail("--duration can't override a plan that uses stages")
        load["duration"] = duration
    elif plan_file is None:
        load.setdefault("duration", "10s")
    data["load"] = load
    if warmup is not None:
        data["warmup"] = warmup
    if insecure:
        data["insecure"] = True

    try:
        return TestPlan.model_validate(data)
    except ValidationError as e:
        err_console.print("[bold red]Invalid test plan:[/]")
        for error in e.errors():
            loc = ".".join(str(p) for p in error["loc"]) or "(root)"
            err_console.print(f"  [red]•[/] {loc}: {error['msg']}")
        raise typer.Exit(2) from None


def _request_from_flags(
    url: str, method: str, headers: list[str], body: str | None
) -> dict[str, Any]:
    request: dict[str, Any] = {"method": method, "url": url, "headers": {}}
    for h in headers:
        name, sep, value = h.partition(":")
        if not sep or not name.strip():
            _fail(f"invalid header {h!r}, expected 'Name: value'")
        request["headers"][name.strip()] = value.strip()
    if body is not None:
        try:
            request["json"] = json.loads(body)
        except ValueError:
            request["body"] = body
    return request


async def _execute(plan: TestPlan, quiet: bool) -> tuple[RunAggregator, RunState]:
    aggregator = RunAggregator(warmup=plan.warmup)
    unit = "vus" if plan.load.mode == "vus" else "rate"

    def on_tick(tick: dict[str, Any]) -> None:
        point = aggregator.add_tick(tick)
        if point is not None and not quiet:
            console.print(_format_point(point, unit))

    engine = Engine(plan, on_tick=on_tick)
    loop = asyncio.get_running_loop()
    presses = 0

    def on_sigint() -> None:
        nonlocal presses
        presses += 1
        if presses == 1:
            console.print("[yellow]Stopping gracefully… press Ctrl+C again to abort.[/]")
            engine.stop()
        else:
            engine.abort()

    try:
        loop.add_signal_handler(signal.SIGINT, on_sigint)
        handler_installed = True
    except (NotImplementedError, RuntimeError):  # e.g. Windows
        handler_installed = False
    try:
        await engine.run()
    finally:
        if handler_installed:
            loop.remove_signal_handler(signal.SIGINT)
    return aggregator, engine.state


def _format_point(point: dict[str, Any], unit: str) -> str:
    o = point["overall"]
    err = o["error_rate"] * 100
    err_style = "red" if err > 0 else "green"
    line = (
        f"[dim]{point['time']:>6.0f}s[/]  {unit} {point['target']:>7.1f}  "
        f"active {point['active_vus'] if unit == 'vus' else point['in_flight']:>5}  "
        f"rps [bold]{o['rps']:>8.1f}[/]  p50 {_ms(o['p50'])}  p95 {_ms(o['p95'])}  "
        f"p99 {_ms(o['p99'])}  [{err_style}]err {err:5.2f}%[/]"
    )
    if point["dropped"]:
        line += f"  [yellow]dropped {point['dropped']}[/]"
    if point["loop_lag_ms"] > _LAG_WARNING_MS:
        line += f"  [yellow]generator lag {point['loop_lag_ms']:.0f}ms[/]"
    return line


def _print_summary(plan: TestPlan, s: dict[str, Any]) -> None:
    table = Table(title="Summary", title_justify="left", padding=(0, 1), box=None)
    for col in ("Step", "Requests", "RPS", "Errors", "p50", "p90", "p95", "p99", "Max"):
        table.add_column(
            col, justify="left" if col == "Step" else "right", no_wrap=True, header_style="bold"
        )

    def row(name: str, d: dict[str, Any], bold: bool = False) -> None:
        lat = d["latency"]
        style = "bold" if bold else None
        table.add_row(
            name,
            f"{d['requests']:,}",
            f"{d['rps']:,.1f}",
            f"{d['error_rate'] * 100:.2f}%",
            *(_ms(lat[k], pad=False) for k in ("p50", "p90", "p95", "p99", "max")),
            style=style,
        )

    for name, d in s["steps"].items():
        row(name, d)
    if len(s["steps"]) != 1:
        row("all", s, bold=True)
    console.print()
    console.print(table)

    console.print(
        f"Measured duration: {s['duration']:.1f}s"
        + (f" (warm-up {plan.warmup:g}s excluded)" if plan.warmup else "")
    )
    if s["status"]:
        codes = ", ".join(f"{k}: {v:,}" for k, v in sorted(s["status"].items()))
        console.print(f"Status codes: {codes}")
    for kind, info in s["errors"].items():
        console.print(f"[red]Error[/] {kind}: {info['count']:,}  [dim]{info['sample'] or ''}[/]")
    if plan.load.mode == "rate":
        svc = s["service_latency"]
        console.print(
            f"[dim]Service time (excluding queueing): p50 {_ms(svc['p50'])}  "
            f"p95 {_ms(svc['p95'])}  p99 {_ms(svc['p99'])}[/]"
        )
    if s["dropped"]:
        console.print(
            f"[yellow]{s['dropped']:,} iterations dropped: max_in_flight "
            f"({plan.load.max_in_flight}) reached. The target can't keep up with this rate.[/]"
        )
    if s["max_loop_lag_ms"] > _LAG_WARNING_MS:
        console.print(
            f"[yellow]Load generator was saturated (event-loop lag up to "
            f"{s['max_loop_lag_ms']:.0f}ms). Results may understate what the target can do.[/]"
        )


def _ms(v: float, pad: bool = True) -> str:
    text = f"{v / 1000:.2f}s" if v >= 1000 else f"{v:.1f}ms"
    return text.rjust(8) if pad else text


def _fail(message: str) -> NoReturn:
    err_console.print(f"[bold red]Error:[/] {message}")
    raise typer.Exit(2)
