import { useEffect, useId, useState } from "react";
import { ApiError, api, type ControlAction, type Limits, type RunDetail } from "../api";

interface Props {
  run: RunDetail;
  limits: Limits | null;
  onError: (message: string | null) => void;
}

/** Slider range: up to 4x the planned peak for room to push harder, capped at the safety limit. */
function sliderMax(run: RunDetail, limits: Limits | null): number {
  const load = run.plan.load as { stages?: { target: number }[] };
  const peak = Math.max(run.target, ...(load.stages ?? []).map((s) => s.target), 1);
  const wanted = Math.max(10, Math.ceil((peak * 4) / 10) * 10);
  if (!limits) return wanted;
  return Math.min(wanted, run.mode === "vus" ? limits.max_vus : limits.max_rate);
}

export function RunControls({ run, limits, onError }: Props) {
  const [busy, setBusy] = useState<ControlAction | null>(null);
  const [draft, setDraft] = useState(String(Math.round(run.target)));
  const [editing, setEditing] = useState(false);
  const inputId = useId();
  const unit = run.mode === "vus" ? "users" : "requests per second";
  const max = sliderMax(run, limits);
  const cap = limits ? (run.mode === "vus" ? limits.max_vus : limits.max_rate) : Infinity;

  useEffect(() => {
    if (!editing) setDraft(String(Math.round(run.target)));
  }, [run.target, editing]);

  async function send(action: ControlAction, value?: number) {
    setBusy(action);
    onError(null);
    try {
      await api.control(run.id, action, value);
    } catch (e) {
      onError(e instanceof ApiError ? [e.message, ...e.details].join(" ") : String(e));
    } finally {
      setBusy(null);
    }
  }

  function applyLoad() {
    const value = Number(draft);
    setEditing(false);
    if (!Number.isFinite(value) || value < 0) {
      onError(`Enter a target of 0 or more ${unit}.`);
      return;
    }
    if (value > cap) {
      onError(`The safety limit is ${cap} ${unit}. You can raise it in Settings.`);
      return;
    }
    if (Math.round(value) !== Math.round(run.target)) void send("set_load", value);
  }

  const paused = run.status === "paused";
  const stopping = run.status === "stopping";

  return (
    <div className="controls">
      <div className="load-control">
        <label htmlFor={inputId} className="field-label">
          Target {unit}
        </label>
        <div className="load-inputs">
          <input
            type="range"
            min={0}
            max={max}
            step={1}
            value={Math.min(Number(draft) || 0, max)}
            aria-label={`Target ${unit} slider`}
            disabled={stopping}
            onChange={(e) => {
              setEditing(true);
              setDraft(e.target.value);
            }}
            onPointerUp={applyLoad}
            onKeyUp={(e) => {
              if (e.key.startsWith("Arrow") || e.key === "Home" || e.key === "End") applyLoad();
            }}
          />
          <input
            id={inputId}
            type="number"
            inputMode="decimal"
            min={0}
            className="load-number"
            value={draft}
            disabled={stopping}
            onChange={(e) => {
              setEditing(true);
              setDraft(e.target.value);
            }}
            onKeyDown={(e) => e.key === "Enter" && applyLoad()}
          />
          <button type="button" className="btn" onClick={applyLoad} disabled={stopping || busy !== null}>
            Apply
          </button>
        </div>
      </div>
      <div className="control-buttons">
        <button
          type="button"
          className="btn"
          disabled={stopping || busy !== null}
          onClick={() => send(paused ? "resume" : "pause")}
        >
          {paused ? "Resume" : "Pause"}
        </button>
        <button
          type="button"
          className="btn"
          disabled={stopping || busy !== null}
          onClick={() => send("stop")}
          title="Stop sending new requests and let in-flight ones finish"
        >
          Stop
        </button>
        <button
          type="button"
          className="btn btn-danger"
          disabled={busy !== null}
          onClick={() => send("abort")}
          title="Cancel in-flight requests immediately"
        >
          Abort
        </button>
      </div>
    </div>
  );
}
