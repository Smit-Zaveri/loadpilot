import { describe, expect, it } from "vitest";
import { buildPlan, defaultForm, parseDuration, parseHeaders, type FormState } from "./plan";

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

  it("allows fractional rates but not fractional users", () => {
    expect(buildPlan(form({ mode: "rate", amount: "0.5" })).errors).toEqual({});
    expect(buildPlan(form({ mode: "vus", amount: "0.5" })).errors.amount).toBeDefined();
  });
});
