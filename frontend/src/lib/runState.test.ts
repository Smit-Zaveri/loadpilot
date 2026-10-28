import { describe, expect, it } from "vitest";
import type { Point, RunDetail, Summary } from "../api";
import { applyMessage } from "./runState";

const stats = { requests: 1, failed: 0, rps: 1, error_rate: 0, status: {}, min: 1, mean: 1, p50: 1, p90: 1, p95: 1, p99: 1, max: 1 };
const point = (t: number, events: Point["events"] = []): Point => ({
  t,
  time: t + 1,
  target: 10,
  active_vus: 10,
  in_flight: 0,
  dropped: 0,
  loop_lag_ms: 0,
  state: "running",
  events,
  overall: stats,
  steps: {},
});
const summary = { requests: 5 } as Summary;
const run = (series: Point[] = []): RunDetail =>
  ({ id: "r", status: "running", series, events: [], summary, target: 10 }) as unknown as RunDetail;

describe("applyMessage", () => {
  it("replaces the run on snapshot and finished", () => {
    const next = run([point(0)]);
    expect(applyMessage(null, { type: "snapshot", run: next })).toBe(next);
    expect(applyMessage(run(), { type: "finished", run: next })).toBe(next);
  });

  it("appends new points and updates live fields", () => {
    const updated = applyMessage(run([point(0)]), {
      type: "point",
      point: point(1, [{ type: "set_load", time: 1.5, value: 20 }]),
      status: "running",
      elapsed: 2,
      summary: { requests: 9 } as Summary,
    });
    expect(updated?.series.map((p) => p.t)).toEqual([0, 1]);
    expect(updated?.elapsed).toBe(2);
    expect(updated?.summary.requests).toBe(9);
    expect(updated?.events).toHaveLength(1);
  });

  it("ignores a point the snapshot already had", () => {
    const start = run([point(0), point(1, [{ type: "pause", time: 1 }])]);
    const updated = applyMessage(start, {
      type: "point",
      point: point(1, [{ type: "pause", time: 1 }]),
      status: "running",
      elapsed: 2,
      summary,
    });
    expect(updated?.series).toHaveLength(2);
    expect(updated?.events).toHaveLength(0);
  });

  it("applies status changes", () => {
    expect(applyMessage(run(), { type: "status", status: "paused", target: 3 })).toMatchObject({
      status: "paused",
      target: 3,
    });
  });

  it("ignores live messages before the run is loaded", () => {
    expect(applyMessage(null, { type: "status", status: "paused", target: 3 })).toBeNull();
  });
});
