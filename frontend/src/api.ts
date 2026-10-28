export type RunStatus =
  | "pending"
  | "running"
  | "paused"
  | "stopping"
  | "finished"
  | "aborted"
  | "failed";

export type LoadMode = "vus" | "rate";
export type ControlAction = "pause" | "resume" | "stop" | "abort" | "set_load";

export interface LatencyStats {
  min: number;
  mean: number;
  p50: number;
  p90: number;
  p95: number;
  p99: number;
  max: number;
}

export interface WindowStats extends LatencyStats {
  requests: number;
  failed: number;
  rps: number;
  error_rate: number;
  status: Record<string, number>;
}

export interface RunEvent {
  type: string;
  time: number;
  value?: number;
}

export interface Point {
  t: number;
  time: number;
  target: number;
  active_vus: number;
  in_flight: number;
  dropped: number;
  loop_lag_ms: number;
  state: RunStatus | null;
  events: RunEvent[];
  overall: WindowStats;
  steps: Record<string, WindowStats>;
}

export interface StepSummary {
  requests: number;
  failed: number;
  error_rate: number;
  rps: number;
  latency: LatencyStats;
  service_latency: LatencyStats;
  status: Record<string, number>;
  errors: Record<string, { count: number; sample: string | null }>;
  bytes_in: number;
}

export interface Summary extends StepSummary {
  duration: number;
  dropped: number;
  max_loop_lag_ms: number;
  steps: Record<string, StepSummary>;
}

interface RunBase {
  id: string;
  name: string;
  status: RunStatus;
  mode: LoadMode;
  target: number;
  elapsed: number;
  total_duration: number;
  created_at: number;
  started_at: number | null;
  ended_at: number | null;
  error: string | null;
}

export interface RunListItem extends RunBase {
  summary: { requests: number; rps: number; error_rate: number; duration: number; p95: number };
}

export interface RunDetail extends RunBase {
  plan: PlanJson;
  summary: Summary;
  series: Point[];
  events: RunEvent[];
}

export interface PlanJson {
  name: string;
  steps: { name: string; request: Record<string, unknown> }[];
  load: Record<string, unknown> & { mode: LoadMode };
  warmup?: number;
  insecure?: boolean;
}

export type StreamMessage =
  | { type: "snapshot"; run: RunDetail }
  | { type: "point"; point: Point; status: RunStatus; elapsed: number; summary: Summary }
  | { type: "status"; status: RunStatus; target: number }
  | { type: "finished"; run: RunDetail };

export interface Health {
  status: string;
  version: string;
  demo: boolean;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly details: string[] = [],
    readonly runId?: string,
  ) {
    super(message);
  }
}

interface FastApiValidationError {
  loc: (string | number)[];
  msg: string;
}

export function describeError(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (status === 422 && Array.isArray(detail)) {
    const lines = (detail as FastApiValidationError[]).map((e) => {
      const loc = e.loc.filter((p) => p !== "body").join(".");
      return loc ? `${loc}: ${e.msg}` : e.msg;
    });
    return new ApiError("The test settings aren't valid.", status, lines);
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    const d = detail as { message: string; run_id?: string };
    return new ApiError(d.message, status, [], d.run_id);
  }
  if (typeof detail === "string") return new ApiError(detail, status);
  return new ApiError(`Request failed (HTTP ${status}).`, status);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(path, {
      ...init,
      headers: { "content-type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("Can't reach the LoadPilot server. Is `loadpilot ui` still running?", 0);
  }
  const body: unknown = await resp.json().catch(() => null);
  if (!resp.ok) throw describeError(resp.status, body);
  return body as T;
}

export const api = {
  health: () => request<Health>("/api/health"),
  listRuns: () => request<RunListItem[]>("/api/runs"),
  getRun: (id: string) => request<RunDetail>(`/api/runs/${encodeURIComponent(id)}`),
  startRun: (plan: PlanJson) =>
    request<RunDetail>("/api/runs", { method: "POST", body: JSON.stringify(plan) }),
  control: (id: string, action: ControlAction, value?: number) =>
    request<RunListItem>(`/api/runs/${encodeURIComponent(id)}/control`, {
      method: "POST",
      body: JSON.stringify(value === undefined ? { action } : { action, value }),
    }),
};

export function runStreamUrl(id: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/runs/${encodeURIComponent(id)}`;
}

export const isDone = (status: RunStatus) =>
  status === "finished" || status === "aborted" || status === "failed";
