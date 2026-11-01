import { describe, expect, it } from "vitest";
import type { PlanJson } from "../api";
import {
  REDACTED,
  buildPlan,
  defaultForm,
  formatDurationInput,
  parseDuration,
  parseHeaders,
  planToForm,
  type FormState,
} from "./plan";

const form = (over: Partial<FormState>): FormState => ({
  ...defaultForm,
  url: "http://localhost:8080/items",
  ...over,
});

describe("parseDuration", () => {
  it.each([
    ["30", 30],
    ["500ms", 0.5],
    ["2m", 120],
    ["1m30s", 90],
    [" 10 s ", 10],
    ["1h", 3600],
  ])("parses %s", (text, seconds) => expect(parseDuration(text)).toBe(seconds));

  it.each(["", "abc", "10x", "-5", "5 minutes"])("rejects %j", (text) =>
    expect(parseDuration(text)).toBeNull(),
  );
});

describe("formatDurationInput", () => {
  it.each([
    [0, "0s"],
    [0.5, "500ms"],
    [30, "30s"],
    [90, "1m30s"],
    [3600, "1h"],
    [3725, "1h2m5s"],
  ])("formats %s seconds", (s, text) => expect(formatDurationInput(s)).toBe(text));

  it("round-trips through parseDuration", () => {
    for (const s of [0.25, 5, 61, 7200]) expect(parseDuration(formatDurationInput(s))).toBe(s);
  });
});

describe("planToForm", () => {
  const saved = (load: Record<string, unknown>, request: Record<string, unknown> = {}): PlanJson => ({
    name: "checkout",
    steps: [{ name: "request", request: { method: "POST", url: "http://x/y", timeout: 10, ...request } }],
    load: { mode: "vus", max_in_flight: 200, ...load } as PlanJson["load"],
    warmup: 5,
    insecure: true,
  });

  it("restores a flat plan (as saved by the server, with expanded shorthand)", () => {
    const { form, notes } = planToForm(
      saved({ vus: 8, duration: 90, start: 8, stages: [{ duration: 90, target: 8 }] }, { json: { a: 1 } }),
    );
    expect(notes).toEqual([]);
    expect(form).toMatchObject({
      name: "checkout",
      method: "POST",
      url: "http://x/y",
      mode: "vus",
      amount: "8",
      rampUp: "0s",
      duration: "1m30s",
      timeout: "10s",
      warmup: "5s",
      maxInFlight: "200",
      insecure: true,
    });
    expect(JSON.parse(form.body)).toEqual({ a: 1 });
  });

  it("restores ramp-up plans built by the form", () => {
    const { form } = planToForm(
      saved({ mode: "rate", stages: [{ duration: 10, target: 40 }, { duration: 20, target: 40 }] }),
    );
    expect(form).toMatchObject({ mode: "rate", amount: "40", rampUp: "10s", duration: "20s" });
  });

  it("explains what it simplified", () => {
    const { form, notes } = planToForm({
      ...saved({ stages: [{ duration: 10, target: 5 }, { duration: 10, target: 20 }, { duration: 5, target: 0 }] }, {
        headers: { Authorization: REDACTED, Accept: "json" },
      }),
      steps: [
        { name: "a", request: { url: "http://x/a", headers: { Authorization: REDACTED, Accept: "json" } } },
        { name: "b", request: { url: "http://x/b" } },
      ],
    });
    expect(form.amount).toBe("20");
    expect(form.duration).toBe("25s");
    expect(form.headers).toBe("Authorization: \nAccept: json");
    expect(notes).toHaveLength(3);
  });

  it("produces a form that builds back into an equivalent plan", () => {
    const original = saved({ vus: 3, duration: 20, start: 3, stages: [{ duration: 20, target: 3 }] });
    const { plan } = buildPlan(planToForm(original).form);
    expect(plan?.load).toMatchObject({ mode: "vus", vus: 3, duration: 20, max_in_flight: 200 });
  });
});

describe("parseHeaders", () => {
  it("parses one header per line and skips blanks", () => {
    expect(parseHeaders("Accept: json\n\nX-Trace:  a:b ")).toEqual({
      headers: { Accept: "json", "X-Trace": "a:b" },
    });
  });
  it("reports the bad line", () => {
    expect(parseHeaders("Accept: json\nbroken").error).toBe('Line 2: use "Name: value".');
  });
});

describe("buildPlan", () => {
  it("builds a flat virtual-user plan", () => {
    const { plan, errors } = buildPlan(form({ amount: "5", duration: "1m" }));
    expect(errors).toEqual({});
    expect(plan).toMatchObject({
      name: "GET http://localhost:8080/items",
      load: { mode: "vus", vus: 5, duration: 60, max_in_flight: 1000 },
      steps: [{ name: "request", request: { method: "GET", timeout: 30 } }],
    });
  });

  it("builds a ramped rate plan", () => {
    const { plan } = buildPlan(form({ mode: "rate", amount: "50", rampUp: "10s", duration: "20s" }));
    expect(plan?.load).toEqual({
      mode: "rate",
      max_in_flight: 1000,
      stages: [
        { duration: 10, target: 50 },
        { duration: 20, target: 50 },
      ],
    });
  });

  it("sends JSON bodies as json and anything else as text", () => {
    expect(buildPlan(form({ method: "POST", body: '{"a":1}' })).plan?.steps[0].request).toMatchObject({
      json: { a: 1 },
    });
    expect(buildPlan(form({ method: "POST", body: "a=1" })).plan?.steps[0].request).toMatchObject({
      body: "a=1",
    });
  });

  it("reports every invalid field", () => {
    const { plan, errors } = buildPlan(
      form({ url: "ftp://x", amount: "1.5", duration: "soon", headers: "nope", maxInFlight: "0" }),
    );
    expect(plan).toBeUndefined();
    expect(Object.keys(errors).sort()).toEqual(["amount", "duration", "headers", "maxInFlight", "url"]);
  });

  it("enforces the safety limits", () => {
    const limits = { max_vus: 50, max_rate: 100, max_duration: 60 };
    expect(buildPlan(form({ amount: "51" }), limits).errors.amount).toBe(
      "The limit is 50 users (change it in Settings).",
    );
    expect(buildPlan(form({ mode: "rate", amount: "101" }), limits).errors.amount).toMatch(/100 req\/s/);
    expect(buildPlan(form({ rampUp: "20s", duration: "50s" }), limits).errors.duration).toMatch(/1m/);
    expect(buildPlan(form({ amount: "50", duration: "1m" }), limits).errors).toEqual({});
  });

  it("allows fractional rates but not fractional users", () => {
    expect(buildPlan(form({ mode: "rate", amount: "0.5" })).errors).toEqual({});
    expect(buildPlan(form({ mode: "vus", amount: "0.5" })).errors.amount).toBeDefined();
  });
});
