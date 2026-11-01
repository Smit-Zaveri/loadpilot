import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import type { AlignedData } from "uplot";
import { isDone, type RunDetail } from "../api";
import { BaselineTag } from "../components/BaselineTag";
import { ResponsesPanel } from "../components/ResponsesPanel";
import { RunActions } from "../components/RunActions";
import { RunControls } from "../components/RunControls";
import { useLimits } from "../hooks/useLimits";
import { StatusBadge } from "../components/StatusBadge";
import { StepTable } from "../components/StepTable";
import { TimeChart } from "../components/TimeChart";
import { useRunStream } from "../hooks/useRunStream";
import {
  formatAxisMs,
  formatAxisNumber,
  formatAxisPercent,
  formatClock,
  formatCount,
  formatMs,
  formatPercent,
  formatRate,
} from "../lib/format";

const LAG_WARNING_MS = 50;

function Metric({
  label,
  value,
  note,
  focal,
  danger,
}: {
  label: string;
  value: string;
  note?: string;
  focal?: boolean;
  danger?: boolean;
}) {
  return (
    <div className={`metric${focal ? " metric-focal" : ""}`}>
      <dt>{label}</dt>
      <dd className={danger ? "text-danger" : undefined}>{value}</dd>
      {note && <dd className="metric-note">{note}</dd>}
    </div>
  );
}

function Metrics({ run }: { run: RunDetail }) {
  const done = isDone(run.status);
  const last = run.series.at(-1);
  const s = run.summary;
  // While running, show the latest second; once finished, the whole run.
  const live = !done && last ? last.overall : null;
  const scope = live ? "last second" : "whole run";
  const users = run.mode === "vus";

  return (
    <dl className="metrics">
      <Metric label="p95 latency" value={formatMs(live?.p95 ?? s.latency.p95)} note={scope} focal />
      <Metric
        label="Requests/s"
        value={formatRate(live?.rps ?? s.rps)}
        note={!users && !done ? `target ${formatRate(run.target)}` : scope}
      />
      <Metric label="p50" value={formatMs(live?.p50 ?? s.latency.p50)} note={scope} />
      <Metric label="p99" value={formatMs(live?.p99 ?? s.latency.p99)} note={scope} />
      <Metric
        label="Failed"
        value={formatPercent(live?.error_rate ?? s.error_rate)}
        note={scope}
        danger={(live?.failed ?? s.failed) > 0}
      />
      <Metric
        label={users ? "Active users" : "In flight"}
        value={last ? formatCount(users ? last.active_vus : last.in_flight) : "0"}
        note={users && !done ? `target ${formatCount(run.target)}` : done ? "at the end" : "now"}
      />
      <Metric label="Requests" value={formatCount(s.requests)} note="whole run" />
    </dl>
  );
}

function Charts({ run }: { run: RunDetail }) {
  const users = run.mode === "vus";
  const data = useMemo(() => {
    const xs = run.series.map((p) => p.time);
    const o = run.series.map((p) => p.overall);
    return {
      throughput: (users
        ? [xs, o.map((w) => w.rps)]
        : [xs, o.map((w) => w.rps), run.series.map((p) => p.target)]) as AlignedData,
      latency: [xs, o.map((w) => w.p50), o.map((w) => w.p95), o.map((w) => w.p99)] as AlignedData,
      failed: [xs, o.map((w) => w.error_rate * 100)] as AlignedData,
      concurrency: (users
        ? [xs, run.series.map((p) => p.active_vus), run.series.map((p) => p.target)]
        : [xs, run.series.map((p) => p.in_flight)]) as AlignedData,
    };
  }, [run.series, users]);

  if (run.series.length === 0) {
    return (
      <p className="panel empty charts-empty">
        {isDone(run.status)
          ? "This run ended before a full second of results was recorded."
          : "Waiting for the first second of results…"}
      </p>
    );
  }

  return (
    <div className="charts">
      <TimeChart
        title="Requests per second"
        data={data.throughput}
        series={
          users
            ? [{ label: "Actual", colorVar: "--series-1" }]
            : [
                { label: "Actual", colorVar: "--series-1" },
                { label: "Target", colorVar: "--series-target", dash: [6, 4] },
              ]
        }
        events={run.events}
        formatValue={formatRate}
        formatAxis={formatAxisNumber}
      />
      <TimeChart
        title="Latency percentiles"
        data={data.latency}
        series={[
          { label: "p50", colorVar: "--series-1" },
          { label: "p95", colorVar: "--series-2" },
          { label: "p99", colorVar: "--series-3" },
        ]}
        events={run.events}
        formatValue={formatMs}
        formatAxis={formatAxisMs}
      />
      <TimeChart
        title="Failed requests (%)"
        data={data.failed}
        series={[{ label: "Failed", colorVar: "--series-3" }]}
        events={run.events}
        formatValue={(v) => formatPercent(v / 100)}
        formatAxis={formatAxisPercent}
      />
      <TimeChart
        title={users ? "Active users" : "Requests in flight"}
        data={data.concurrency}
        series={
          users
            ? [
                { label: "Active", colorVar: "--series-1" },
                { label: "Target", colorVar: "--series-target", dash: [6, 4] },
              ]
            : [{ label: "In flight", colorVar: "--series-1" }]
        }
        events={run.events}
        formatValue={(v) => formatCount(v)}
        formatAxis={formatAxisNumber}
      />
    </div>
  );
}

function Warnings({ run }: { run: RunDetail }) {
  const done = isDone(run.status);
  const lag = done ? run.summary.max_loop_lag_ms : (run.series.at(-1)?.loop_lag_ms ?? 0);
  const maxInFlight = (run.plan.load as { max_in_flight?: number }).max_in_flight;
  return (
    <>
      {lag > LAG_WARNING_MS && (
        <p className="alert alert-warn" role="status">
          The load generator is overloaded (event-loop lag {formatMs(lag)}). These numbers may
          understate what the target can handle. Lower the load to get reliable results.
        </p>
      )}
      {run.summary.dropped > 0 && (
        <p className="alert alert-warn" role="status">
          {formatCount(run.summary.dropped)} scheduled requests were dropped because{" "}
          {maxInFlight ? formatCount(maxInFlight) : "the maximum number of"} requests were already in
          flight. The target can't keep up with this rate.
        </p>
      )}
      {run.error && (
        <p className="alert alert-error" role="alert">
          The run failed: {run.error}
        </p>
      )}
    </>
  );
}

export function RunPage() {
  const { id = "" } = useParams();
  const { run, state, error, setRun } = useRunStream(id);
  const [controlError, setControlError] = useState<string | null>(null);
  const limits = useLimits();

  if (state === "loading") return <p className="page-state">Loading run…</p>;

  if (state === "error" || !run) {
    const notFound = error?.status === 404;
    return (
      <div className="page-state">
        <h1 className="page-title">{notFound ? "Run not found" : "Couldn't load this run"}</h1>
        <p className="muted">
          {notFound ? "It may have been deleted. Saved runs are listed in History." : error?.message}
        </p>
        <Link to="/" className="btn">
          Start a new test
        </Link>
      </div>
    );
  }

  const done = isDone(run.status);
  const firstRequest = run.plan.steps[0]?.request as { method?: string; url?: string } | undefined;
  const progress = run.total_duration > 0 ? Math.min(1, run.elapsed / run.total_duration) : 0;

  return (
    <div className="run-page">
      <header className="run-head">
        <div className="run-title">
          <h1 className="page-title">{run.name}</h1>
          <StatusBadge status={run.status} />
          {run.is_baseline && <BaselineTag />}
        </div>
        {firstRequest && (
          <p className="run-target">
            <span className="method">{firstRequest.method}</span> {firstRequest.url}
            {run.plan.steps.length > 1 && ` + ${run.plan.steps.length - 1} more step(s)`}
          </p>
        )}
        <div className="run-progress">
          <span className="num">
            {formatClock(run.elapsed)} / {formatClock(run.total_duration)}
          </span>
          <progress max={1} value={progress} aria-label="Run progress" />
          {state === "reconnecting" && <span className="text-warn">Connection lost, reconnecting…</span>}
        </div>
      </header>

      {!done && <RunControls run={run} limits={limits} onError={setControlError} />}
      {done && <RunActions run={run} onChange={setRun} />}
      {run.status === "interrupted" && (
        <p className="alert alert-warn" role="status">
          The LoadPilot server stopped while this test was running. Results below cover the time
          before it stopped.
        </p>
      )}
      {controlError && (
        <p className="alert alert-error" role="alert">
          {controlError}
        </p>
      )}
      <Warnings run={run} />

      <Metrics run={run} />
      <Charts run={run} />

      <section className="panel" aria-labelledby="steps-h">
        <h2 id="steps-h" className="panel-title">
          Steps{" "}
          <span className="muted small">
            whole run{run.plan.warmup ? `, excluding ${run.plan.warmup}s warm-up` : ""}
          </span>
        </h2>
        <StepTable summary={run.summary} />
      </section>
      <section className="panel" aria-label="Responses">
        <ResponsesPanel summary={run.summary} />
      </section>
    </div>
  );
}
