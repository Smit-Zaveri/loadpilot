import type { LoadMode, PlanJson } from "../api";

export const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] as const;

export interface FormState {
  name: string;
  method: (typeof METHODS)[number];
  url: string;
  mode: LoadMode;
  amount: string;
  rampUp: string;
  duration: string;
  headers: string;
  body: string;
  timeout: string;
  warmup: string;
  maxInFlight: string;
  insecure: boolean;
}

export type FieldErrors = Partial<Record<keyof FormState, string>>;

export const defaultForm: FormState = {
  name: "",
  method: "GET",
  url: "",
  mode: "vus",
  amount: "10",
  rampUp: "0s",
  duration: "30s",
  headers: "",
  body: "",
  timeout: "30s",
  warmup: "0s",
  maxInFlight: "1000",
  insecure: false,
};

const UNITS: Record<string, number> = { ms: 0.001, s: 1, m: 60, h: 3600 };

/** Same rules as the backend: "30", "500ms", "2m", "1m30s". Returns seconds or null. */
export function parseDuration(text: string): number | null {
  const t = text.trim().replace(/\s+/g, "");
  if (t === "") return null;
  if (/^\d+(\.\d+)?$/.test(t)) return Number(t);
  if (!/^(\d+(\.\d+)?(ms|h|m|s))+$/.test(t)) return null;
  let total = 0;
  for (const [, n, unit] of t.matchAll(/(\d+(?:\.\d+)?)(ms|h|m|s)/g)) {
    total += Number(n) * UNITS[unit];
  }
  return total;
}

export function parseHeaders(text: string): { headers: Record<string, string>; error?: string } {
  const headers: Record<string, string> = {};
  for (const [i, raw] of text.split("\n").entries()) {
    const line = raw.trim();
    if (!line) continue;
    const idx = line.indexOf(":");
    if (idx <= 0) return { headers, error: `Line ${i + 1}: use "Name: value".` };
    headers[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
  }
  return { headers };
}

export function buildPlan(f: FormState): { plan?: PlanJson; errors: FieldErrors } {
  const errors: FieldErrors = {};

  const url = f.url.trim();
  if (!url) errors.url = "Enter the URL to test.";
  else if (!/^https?:\/\/\S+$/i.test(url)) errors.url = "The URL must start with http:// or https://.";

  const amount = Number(f.amount);
  if (f.amount.trim() === "" || !Number.isFinite(amount) || amount <= 0) {
    errors.amount = f.mode === "vus" ? "Enter how many users, 1 or more." : "Enter a rate above 0.";
  } else if (f.mode === "vus" && !Number.isInteger(amount)) {
    errors.amount = "Users must be a whole number.";
  }

  const duration = parseDuration(f.duration);
  if (duration === null || duration <= 0) errors.duration = "Use a duration like 30s, 2m or 1m30s.";

  const rampUp = f.rampUp.trim() === "" ? 0 : parseDuration(f.rampUp);
  if (rampUp === null) errors.rampUp = "Use a duration like 10s, or 0s for no ramp.";

  const timeout = parseDuration(f.timeout);
  if (timeout === null || timeout <= 0) errors.timeout = "Use a timeout like 30s.";

  const warmup = f.warmup.trim() === "" ? 0 : parseDuration(f.warmup);
  if (warmup === null) errors.warmup = "Use a duration like 5s, or 0s.";

  const maxInFlight = Number(f.maxInFlight);
  if (!Number.isInteger(maxInFlight) || maxInFlight < 1) {
    errors.maxInFlight = "Enter a whole number, 1 or more.";
  }

  const { headers, error: headerError } = parseHeaders(f.headers);
  if (headerError) errors.headers = headerError;

  if (Object.keys(errors).length > 0) return { errors };

  const request: Record<string, unknown> = { method: f.method, url, headers, timeout };
  const body = f.body.trim();
  if (body) {
    try {
      request.json = JSON.parse(body);
    } catch {
      request.body = f.body;
    }
  }

  const load: PlanJson["load"] = { mode: f.mode, max_in_flight: maxInFlight };
  if (rampUp && rampUp > 0) {
    load.stages = [
      { duration: rampUp, target: amount },
      { duration: duration!, target: amount },
    ];
  } else {
    load[f.mode] = amount;
    load.duration = duration;
  }

  return {
    errors,
    plan: {
      name: f.name.trim() || `${f.method} ${url}`,
      steps: [{ name: "request", request }],
      load,
      warmup: warmup ?? 0,
      insecure: f.insecure,
    },
  };
}
