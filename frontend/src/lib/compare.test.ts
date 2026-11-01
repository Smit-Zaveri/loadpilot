import { describe, expect, it } from "vitest";
import type { RunDetail } from "../api";
import { METRICS, describeDelta, pickReference } from "./compare";

const metric = (label: string) => METRICS.find((m) => m.label === label)!;

describe("describeDelta", () => {
  it("describes latency as slower or faster", () => {
    expect(describeDelta(metric("p95 latency"), 118, 100)).toEqual({ text: "18% slower", verdict: "worse" });
    expect(describeDelta(metric("p95 latency"), 95, 100)).toEqual({ text: "5.0% faster", verdict: "better" });
  });

  it("describes throughput as higher or lower", () => {
    expect(describeDelta(metric("Requests/s"), 150, 100)).toEqual({ text: "50% higher", verdict: "better" });
    expect(describeDelta(metric("Requests/s"), 80, 100)).toEqual({ text: "20% lower", verdict: "worse" });
  });

  it("treats changes under 2% as the same (run-to-run noise)", () => {
    expect(describeDelta(metric("p95 latency"), 101.9, 100).verdict).toBe("same");
    expect(describeDelta(metric("Requests/s"), 29.4, 29.7).verdict).toBe("same");
    expect(describeDelta(metric("p95 latency"), 102.5, 100).verdict).toBe("worse");
  });

  it("compares failure rates in percentage points", () => {
    expect(describeDelta(metric("Failed"), 0.015, 0.01)).toEqual({ text: "+0.50 pts", verdict: "worse" });
    expect(describeDelta(metric("Failed"), 0, 0.02)).toEqual({ text: "−2.00 pts", verdict: "better" });
    expect(describeDelta(metric("Failed"), 0, 0).verdict).toBe("same");
  });

  it("has no verdict for neutral metrics or a zero reference", () => {
    expect(describeDelta(metric("Requests"), 200, 100).verdict).toBe("none");
    expect(describeDelta(metric("p95 latency"), 5, 0)).toEqual({ text: "–", verdict: "none" });
  });
});

describe("pickReference", () => {
  const run = (id: string, created_at: number, is_baseline = false) =>
    ({ id, created_at, is_baseline }) as RunDetail;

  it("prefers the baseline", () => {
    expect(pickReference([run("a", 1), run("b", 2, true)])?.id).toBe("b");
  });
  it("falls back to the oldest run", () => {
    expect(pickReference([run("new", 5), run("old", 1)])?.id).toBe("old");
  });
});
