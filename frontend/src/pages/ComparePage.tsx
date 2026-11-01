import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import uPlot, { type AlignedData } from "uplot";
import { ApiError, api, type RunDetail } from "../api";
import { BaselineTag } from "../components/BaselineTag";
import { TimeChart } from "../components/TimeChart";
import { METRICS, describeDelta, pickReference } from "../lib/compare";
import { formatAxisMs, formatAxisNumber, formatMs, formatRate, formatTime } from "../lib/format";

const SERIES_VARS = ["--series-1", "--series-2", "--series-3", "--series-4"];

function runLabel(r: RunDetail, i: number): string {
  return `${String.fromCharCode(65 + i)}: ${r.name}`;
}

/** Aligns each run's per-second series on a shared x axis (seconds since start). */
function overlay(runs: RunDetail[], pick: (p: RunDetail["series"][number]) => number): AlignedData {
  const tables = runs.map(
    (r) => [r.series.map((p) => p.time), r.series.map(pick)] as AlignedData,
  );
  return tables.length === 1 ? tables[0] : uPlot.join(tables);
}

export function ComparePage() {
  const [params] = useSearchParams();
  const ids = useMemo(
    () => [...new Set((params.get("ids") ?? "").split(",").filter(Boolean))].slice(0, 4),
    [params],
  );
  const [runs, setRuns] = useState<RunDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRuns(null);
    setError(null);
    if (ids.length < 2) return;
    Promise.all(ids.map((id) => api.getRun(id)))
      .then(setRuns)
      .catch((e: unknown) =>
        setError(
          e instanceof ApiError && e.status === 404
            ? "One of these runs no longer exists."
            : e instanceof Error
              ? e.message
              : String(e),
        ),
      );
  }, [ids]);

  const chartData = useMemo(
    () =>
      runs && {
        p95: overlay(runs, (p) => p.overall.p95),
        rps: overlay(runs, (p) => p.overall.rps),
      },
    [runs],
  );

  if (ids.length < 2) {
    return (
      <div className="page-state">
        <h1 className="page-title">Compare runs</h1>
        <p className="muted">Pick 2 to 4 runs in History to compare them.</p>
        <Link to="/history" className="btn">
          Open History
        </Link>
      </div>
    );
  }
  if (error) {
    return (
      <div className="page-state">
        <h1 className="page-title">Compare runs</h1>
        <p className="alert alert-error" role="alert">
          {error}
        </p>
        <Link to="/history" className="btn">
          Back to History
        </Link>
      </div>
    );
  }
  if (!runs || !chartData) return <p className="page-state">Loading runs…</p>;

  const reference = pickReference(runs)!;
  const series = runs.map((r, i) => ({
    label: runLabel(r, i),
    colorVar: SERIES_VARS[i],
    spanGaps: true,
  }));

  return (
    <div className="compare">
      <div className="page-head">
        <h1 className="page-title">Compare {runs.length} runs</h1>
        <Link to="/history" className="btn">
          Back to History
        </Link>
      </div>
      <p className="muted">
        Differences are against <strong>{runLabel(reference, runs.indexOf(reference))}</strong>
        {reference.is_baseline ? ", the baseline." : ", the oldest run (no baseline selected)."}
        {new Set(runs.map((r) => r.name)).size > 1 &&
          " These runs come from different tests, so large differences are expected."}
      </p>

      <div className="panel">
        <div className="table-scroll">
          <table className="data-table compare-table" aria-label="Comparison">
            <thead>
              <tr>
                <th scope="col">Metric</th>
                {runs.map((r, i) => (
                  <th scope="col" key={r.id}>
                    <span className="compare-run">
                      <span className="swatch" style={{ background: `var(${SERIES_VARS[i]})` }} aria-hidden="true" />
                      <Link to={`/runs/${r.id}`}>{runLabel(r, i)}</Link>
                    </span>
                    <span className="compare-meta">
                      {formatTime(r.created_at)}
                      {r.is_baseline && <BaselineTag />}
                      {r === reference && !r.is_baseline && <span className="tag">Reference</span>}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {METRICS.map((m) => {
                const ref = m.value(reference);
                return (
                  <tr key={m.label}>
                    <th scope="row">{m.label}</th>
                    {runs.map((r) => {
                      const v = m.value(r);
                      const delta = r === reference ? null : describeDelta(m, v, ref);
                      return (
                        <td key={r.id}>
                          <span className="num">{m.format(v)}</span>
                          {delta && delta.verdict !== "none" && (
                            <span className={`delta delta-${delta.verdict}`}>{delta.text}</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="charts">
        <TimeChart
          title="p95 latency over time"
          data={chartData.p95}
          series={series}
          formatValue={formatMs}
          formatAxis={formatAxisMs}
        />
        <TimeChart
          title="Requests per second over time"
          data={chartData.rps}
          series={series}
          formatValue={formatRate}
          formatAxis={formatAxisNumber}
        />
      </div>
    </div>
  );
}
