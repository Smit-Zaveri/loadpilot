import { useEffect, useId, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError, api, type Health, type RunListItem } from "../api";
import { StatusBadge } from "../components/StatusBadge";
import { formatCount, formatMs, formatPercent, formatTime } from "../lib/format";
import {
  METHODS,
  buildPlan,
  defaultForm,
  parseDuration,
  type FieldErrors,
  type FormState,
} from "../lib/plan";

function Field({
  label,
  hint,
  error,
  children,
  id,
}: {
  label: string;
  hint?: string;
  error?: string;
  id: string;
  children: (describedBy: string | undefined) => ReactNode;
}) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className="field">
      <label htmlFor={id} className="field-label">
        {label}
      </label>
      {children(describedBy)}
      {hint && (
        <p id={hintId} className="field-hint">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="field-error">
          {error}
        </p>
      )}
    </div>
  );
}

function RecentRuns() {
  const [runs, setRuns] = useState<RunListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .listRuns()
        .then((r) => {
          if (cancelled) return;
          setRuns(r);
          setError(null);
        })
        .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : String(e)));
    void load();
    const timer = setInterval(load, 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <section className="panel recent" aria-labelledby="recent-h">
      <h2 id="recent-h" className="panel-title">
        This session
      </h2>
      <p className="muted small">Runs are kept in memory until the server restarts.</p>
      {error && runs === null ? (
        <p className="alert alert-error" role="alert">
          Couldn't load runs. {error}
        </p>
      ) : runs === null ? (
        <p className="muted">Loading runs…</p>
      ) : runs.length === 0 ? (
        <p className="empty">No runs yet. Fill in a URL and start a test; it will appear here.</p>
      ) : (
        <ul className="run-list">
          {runs.map((r) => (
            <li key={r.id}>
              <Link to={`/runs/${r.id}`} className="run-link">
                <span className="run-link-top">
                  <span className="run-name">{r.name}</span>
                  <StatusBadge status={r.status} />
                </span>
                <span className="run-meta">
                  <span>{formatTime(r.created_at)}</span>
                  <span>{formatCount(r.summary.requests)} req</span>
                  <span>p95 {formatMs(r.summary.p95)}</span>
                  <span className={r.summary.error_rate > 0 ? "text-danger" : undefined}>
                    {formatPercent(r.summary.error_rate)} failed
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function NewTestPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState<FormState>(defaultForm);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitError, setSubmitError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const id = useId();

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  function fillDemo() {
    setForm((f) => ({
      ...f,
      name: "Demo: random latency",
      method: "GET",
      url: `${window.location.origin}/demo/random-latency?min_ms=20&max_ms=120`,
      body: "",
    }));
    setErrors({});
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    const { plan, errors: errs } = buildPlan(form);
    setErrors(errs);
    if (!plan) return;
    setSubmitting(true);
    try {
      const run = await api.startRun(plan);
      navigate(`/runs/${run.id}`);
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err : new ApiError(String(err), 0));
      setSubmitting(false);
    }
  }

  const isRate = form.mode === "rate";
  const errorCount = Object.keys(errors).length;

  return (
    <div className="new-test">
      <form className="panel test-form" onSubmit={onSubmit} noValidate aria-labelledby="form-h">
        <h1 id="form-h" className="page-title">
          New test
        </h1>

        <div className="request-row">
          <Field label="Method" id={`${id}-method`}>
            {() => (
              <select
                id={`${id}-method`}
                value={form.method}
                onChange={(e) => set("method", e.target.value as FormState["method"])}
              >
                {METHODS.map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            )}
          </Field>
          <Field label="URL" id={`${id}-url`} error={errors.url}>
            {(describedBy) => (
              <input
                id={`${id}-url`}
                className="url-input"
                type="url"
                placeholder="https://api.example.com/v1/items"
                value={form.url}
                aria-invalid={Boolean(errors.url)}
                aria-describedby={describedBy}
                onChange={(e) => set("url", e.target.value)}
                autoFocus
              />
            )}
          </Field>
        </div>
        {health?.demo && (
          <p className="demo-hint">
            No API handy?{" "}
            <button type="button" className="link-btn" onClick={fillDemo}>
              Fill in the built-in demo target
            </button>
            . It runs inside LoadPilot, so use it to try the tool, not to benchmark.
          </p>
        )}

        <fieldset className="mode">
          <legend className="field-label">Load model</legend>
          <div className="segmented">
            <label className={!isRate ? "selected" : undefined}>
              <input
                type="radio"
                name="mode"
                value="vus"
                checked={!isRate}
                onChange={() => set("mode", "vus")}
              />
              Virtual users
            </label>
            <label className={isRate ? "selected" : undefined}>
              <input
                type="radio"
                name="mode"
                value="rate"
                checked={isRate}
                onChange={() => set("mode", "rate")}
              />
              Requests per second
            </label>
          </div>
          <p className="field-hint">
            {isRate
              ? "Requests start on a fixed schedule whether or not earlier ones have finished. Latency then includes any queueing, which is the honest number."
              : "Each user sends a request, waits for the reply, then sends the next. If the API slows down, the load drops with it."}
          </p>
        </fieldset>

        <div className="load-row">
          <Field
            label={isRate ? "Target rate (req/s)" : "Number of users"}
            id={`${id}-amount`}
            error={errors.amount}
          >
            {(describedBy) => (
              <input
                id={`${id}-amount`}
                type="number"
                inputMode="decimal"
                min={isRate ? 0.1 : 1}
                step={isRate ? "any" : 1}
                value={form.amount}
                aria-invalid={Boolean(errors.amount)}
                aria-describedby={describedBy}
                onChange={(e) => set("amount", e.target.value)}
              />
            )}
          </Field>
          <Field label="Ramp-up" id={`${id}-ramp`} hint="0s starts at full load" error={errors.rampUp}>
            {(describedBy) => (
              <input
                id={`${id}-ramp`}
                value={form.rampUp}
                aria-invalid={Boolean(errors.rampUp)}
                aria-describedby={describedBy}
                onChange={(e) => set("rampUp", e.target.value)}
              />
            )}
          </Field>
          <Field
            label={(parseDuration(form.rampUp) ?? 0) > 0 ? "Then hold for" : "Duration"}
            id={`${id}-duration`}
            hint="e.g. 30s, 2m, 1m30s"
            error={errors.duration}
          >
            {(describedBy) => (
              <input
                id={`${id}-duration`}
                value={form.duration}
                aria-invalid={Boolean(errors.duration)}
                aria-describedby={describedBy}
                onChange={(e) => set("duration", e.target.value)}
              />
            )}
          </Field>
        </div>

        <details className="more">
          <summary>Headers, body and timeout</summary>
          <Field label="Headers" id={`${id}-headers`} hint='One per line, "Name: value"' error={errors.headers}>
            {(describedBy) => (
              <textarea
                id={`${id}-headers`}
                rows={3}
                spellCheck={false}
                placeholder="Authorization: Bearer <token>"
                value={form.headers}
                aria-invalid={Boolean(errors.headers)}
                aria-describedby={describedBy}
                onChange={(e) => set("headers", e.target.value)}
              />
            )}
          </Field>
          <Field label="Body" id={`${id}-body`} hint="JSON is sent as application/json; anything else as plain text">
            {(describedBy) => (
              <textarea
                id={`${id}-body`}
                rows={4}
                spellCheck={false}
                value={form.body}
                aria-describedby={describedBy}
                onChange={(e) => set("body", e.target.value)}
              />
            )}
          </Field>
          <Field label="Timeout" id={`${id}-timeout`} error={errors.timeout}>
            {(describedBy) => (
              <input
                id={`${id}-timeout`}
                className="short"
                value={form.timeout}
                aria-invalid={Boolean(errors.timeout)}
                aria-describedby={describedBy}
                onChange={(e) => set("timeout", e.target.value)}
              />
            )}
          </Field>
        </details>

        <details className="more">
          <summary>Run options</summary>
          <Field label="Name" id={`${id}-name`} hint="Defaults to the method and URL">
            {(describedBy) => (
              <input
                id={`${id}-name`}
                value={form.name}
                aria-describedby={describedBy}
                onChange={(e) => set("name", e.target.value)}
              />
            )}
          </Field>
          <Field
            label="Warm-up"
            id={`${id}-warmup`}
            hint="Left out of the summary, so cold caches don't skew results"
            error={errors.warmup}
          >
            {(describedBy) => (
              <input
                id={`${id}-warmup`}
                className="short"
                value={form.warmup}
                aria-invalid={Boolean(errors.warmup)}
                aria-describedby={describedBy}
                onChange={(e) => set("warmup", e.target.value)}
              />
            )}
          </Field>
          <Field
            label="Max requests in flight"
            id={`${id}-inflight`}
            hint="Beyond this, scheduled requests are dropped and counted"
            error={errors.maxInFlight}
          >
            {(describedBy) => (
              <input
                id={`${id}-inflight`}
                className="short"
                type="number"
                min={1}
                value={form.maxInFlight}
                aria-invalid={Boolean(errors.maxInFlight)}
                aria-describedby={describedBy}
                onChange={(e) => set("maxInFlight", e.target.value)}
              />
            )}
          </Field>
          <label className="check">
            <input
              type="checkbox"
              checked={form.insecure}
              onChange={(e) => set("insecure", e.target.checked)}
            />
            Skip TLS certificate checks (self-signed certificates)
          </label>
        </details>

        {errorCount > 0 && (
          <p className="alert alert-error" role="alert">
            Fix the {errorCount === 1 ? "highlighted field" : `${errorCount} highlighted fields`} to start.
          </p>
        )}
        {submitError && (
          <div className="alert alert-error" role="alert">
            <p>{submitError.message}</p>
            {submitError.details.length > 0 && (
              <ul>
                {submitError.details.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            )}
            {submitError.runId && (
              <p>
                <Link to={`/runs/${submitError.runId}`}>Open the running test</Link> to stop it first.
              </p>
            )}
          </div>
        )}

        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? "Starting…" : "Start test"}
          </button>
        </div>
      </form>

      <RecentRuns />
    </div>
  );
}
