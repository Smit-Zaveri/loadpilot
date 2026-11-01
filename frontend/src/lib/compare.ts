import type { RunDetail } from "../api";
import { formatCount, formatMs, formatPercent, formatRate } from "./format";

export type Direction = "lower" | "higher" | "neutral";
export type Verdict = "better" | "worse" | "same" | "none";

export interface MetricDef {
  label: string;
  /** Which way is better. */
  better: Direction;
  value: (r: RunDetail) => number;
  format: (v: number) => string;
  /** Compare in percentage points instead of relative change (for rates like errors). */
  points?: boolean;
}

export const METRICS: MetricDef[] = [
  { label: "Requests/s", better: "higher", value: (r) => r.summary.rps, format: formatRate },
  { label: "p50 latency", better: "lower", value: (r) => r.summary.latency.p50, format: formatMs },
  { label: "p95 latency", better: "lower", value: (r) => r.summary.latency.p95, format: formatMs },
  { label: "p99 latency", better: "lower", value: (r) => r.summary.latency.p99, format: formatMs },
  { label: "Max latency", better: "lower", value: (r) => r.summary.latency.max, format: formatMs },
  {
    label: "Failed",
    better: "lower",
    value: (r) => r.summary.error_rate,
    format: formatPercent,
    points: true,
  },
  { label: "Requests", better: "neutral", value: (r) => r.summary.requests, format: formatCount },
  { label: "Duration", better: "neutral", value: (r) => r.summary.duration, format: (v) => `${v.toFixed(1)} s` },
];

/** Relative changes smaller than this count as "same": run-to-run noise is about this size. */
const SAME_THRESHOLD = 0.02;

export interface Delta {
  text: string;
  verdict: Verdict;
}

/** Describes `value` relative to `reference` in words, e.g. "18% slower". */
export function describeDelta(metric: MetricDef, value: number, reference: number): Delta {
  if (metric.points) {
    const diff = value - reference;
    if (Math.abs(diff) < 0.0001) return { text: "same", verdict: "same" };
    const pts = `${diff > 0 ? "+" : "−"}${Math.abs(diff * 100).toFixed(2)} pts`;
    return { text: pts, verdict: verdictFor(metric.better, diff) };
  }
  if (reference === 0) return { text: "–", verdict: "none" };
  const rel = (value - reference) / reference;
  if (Math.abs(rel) < SAME_THRESHOLD) return { text: "same", verdict: "same" };
  const pct = `${Math.abs(rel * 100).toFixed(Math.abs(rel) < 0.1 ? 1 : 0)}%`;
  const words =
    metric.better === "lower"
      ? rel > 0 ? "slower" : "faster"
      : rel > 0 ? "higher" : "lower";
  return { text: `${pct} ${words}`, verdict: verdictFor(metric.better, rel) };
}

function verdictFor(better: Direction, diff: number): Verdict {
  if (better === "neutral") return "none";
  const improved = better === "lower" ? diff < 0 : diff > 0;
  return improved ? "better" : "worse";
}

/** The reference is the baseline if one is selected, otherwise the oldest run. */
export function pickReference(runs: RunDetail[]): RunDetail | undefined {
  return runs.find((r) => r.is_baseline) ?? [...runs].sort((a, b) => a.created_at - b.created_at)[0];
}
