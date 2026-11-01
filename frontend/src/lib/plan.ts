import type { Limits, LoadMode, PlanJson } from "../api";

/** Matches the backend's mask for secret-looking header values. */
export const REDACTED = "••••••";

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

/** 90 -> "1m30s", 30 -> "30s", 0.5 -> "500ms", 3600 -> "1h". */
export function formatDurationInput(seconds: number): string {
  if (seconds > 0 && seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  let rest = Math.round(seconds);
  const parts: string[] = [];
  for (const [unit, size] of [["h", 3600], ["m", 60]] as const) {
    if (rest >= size) {
      parts.push(`${Math.floor(rest / size)}${unit}`);
      rest %= size;
    }
  }
  if (rest > 0 || parts.length === 0) parts.push(`${rest}s`);
  return parts.join("");
}

interface StoredLoad {
  mode: LoadMode;
  vus?: number | null;
  rate?: number | null;
  duration?: number | null;
  start?: number | null;
  stages?: { duration: number; target: number }[];
  max_in_flight?: number;
}

/**
 * Turns a saved plan back into form values for "Run again".
 * `notes` explains anything the form can't represent exactly.
 */
export function planToForm(plan: PlanJson): { form: FormState; notes: string[] } {
  const notes: string[] = [];
  const req = (plan.steps[0]?.request ?? {}) as {
    method?: string;
    url?: string;
    headers?: Record<string, string>;
    json?: unknown;
    body?: string | null;
    timeout?: number;
  };
  if (plan.steps.length > 1) {
    notes.push(`This test had ${plan.steps.length} steps; only the first one is filled in.`);
  }
  const headers = Object.entries(req.headers ?? {});
  if (headers.some(([, v]) => v === REDACTED)) {
    notes.push("Secret header values aren't saved. Re-enter them before starting.");
  }

  const load = plan.load as StoredLoad;
  const level = load.mode === "vus" ? load.vus : load.rate;
  const stages = load.stages ?? [];
  let amount = 10;
  let rampUp = 0;
  let duration = 30;
  if (level != null && load.duration != null) {
    amount = level;
    duration = load.duration;
  } else if (
    stages.length === 2 &&
    !load.start &&
    stages[0].target === stages[1].target
  ) {
    amount = stages[0].target;
    rampUp = stages[0].duration;
    duration = stages[1].duration;
  } else if (stages.length > 0) {
    amount = Math.max(...stages.map((s) => s.target));
    duration = stages.reduce((sum, s) => sum + s.duration, 0);
    notes.push(
      `This test used ${stages.length} load stages; the form holds its peak for the same total time.`,
    );
  }

  const method = (req.method ?? "GET").toUpperCase();
  const form: FormState = {
    ...defaultForm,
    name: plan.name,
    method: (METHODS as readonly string[]).includes(method)
      ? (method as FormState["method"])
      : "GET",
    url: req.url ?? "",
    mode: load.mode,
    amount: String(amount),
    rampUp: formatDurationInput(rampUp),
    duration: formatDurationInput(duration),
    headers: headers.map(([k, v]) => `${k}: ${v === REDACTED ? "" : v}`).join("\n"),
    body:
      req.json != null ? JSON.stringify(req.json, null, 2) : typeof req.body === "string" ? req.body : "",
    timeout: formatDurationInput(req.timeout ?? 30),
    warmup: formatDurationInput(plan.warmup ?? 0),
    maxInFlight: String(load.max_in_flight ?? 1000),
    insecure: Boolean(plan.insecure),
  };
  return { form, notes };
}

export function buildPlan(f: FormState, limits?: Limits): { plan?: PlanJson; errors: FieldErrors } {
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

  if (limits) {
    if (!errors.amount && f.mode === "vus" && amount > limits.max_vus) {
      errors.amount = `The limit is ${limits.max_vus} users (change it in Settings).`;
    }
    if (!errors.amount && f.mode === "rate" && amount > limits.max_rate) {
      errors.amount = `The limit is ${limits.max_rate} req/s (change it in Settings).`;
    }
    const total = (rampUp ?? 0) + (duration ?? 0);
    if (!errors.duration && !errors.rampUp && total > limits.max_duration) {
      errors.duration = `The total time limit is ${formatDurationInput(limits.max_duration)} (change it in Settings).`;
    }
  }

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
