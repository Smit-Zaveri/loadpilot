import { useEffect, useId, useState, type FormEvent } from "react";
import { ApiError, api, type Limits } from "../api";
import { formatDurationInput, parseDuration } from "../lib/plan";

interface Draft {
  maxVus: string;
  maxRate: string;
  maxDuration: string;
}

const toDraft = (l: Limits): Draft => ({
  maxVus: String(l.max_vus),
  maxRate: String(l.max_rate),
  maxDuration: formatDurationInput(l.max_duration),
});

export function SettingsPage() {
  const id = useId();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Partial<Record<keyof Draft, string>>>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .getSettings()
      .then((s) => setDraft(toDraft(s.limits)))
      .catch((e: unknown) => setLoadError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  if (loadError) {
    return (
      <div className="page-state">
        <h1 className="page-title">Settings</h1>
        <p className="alert alert-error" role="alert">
          Couldn't load settings. {loadError}
        </p>
      </div>
    );
  }
  if (!draft) return <p className="page-state">Loading settings…</p>;

  const set = (key: keyof Draft, value: string) => {
    setSaved(false);
    setDraft({ ...draft, [key]: value });
  };

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!draft) return;
    const next: typeof errors = {};
    const vus = Number(draft.maxVus);
    const rate = Number(draft.maxRate);
    const duration = parseDuration(draft.maxDuration);
    if (!Number.isInteger(vus) || vus < 1) next.maxVus = "Enter a whole number, 1 or more.";
    if (!Number.isFinite(rate) || rate <= 0) next.maxRate = "Enter a number above 0.";
    if (duration === null || duration <= 0) next.maxDuration = "Use a duration like 30m or 2h.";
    setErrors(next);
    if (Object.keys(next).length) return;

    setSaving(true);
    setSaveError(null);
    try {
      const res = await api.putSettings({ max_vus: vus, max_rate: rate, max_duration: duration! });
      setDraft(toDraft(res.limits));
      setSaved(true);
    } catch (err) {
      const apiErr = err instanceof ApiError ? err : null;
      setSaveError([apiErr?.message ?? String(err), ...(apiErr?.details ?? [])].join(" "));
    } finally {
      setSaving(false);
    }
  }

  const field = (key: keyof Draft, label: string, hint: string, type: "number" | "text") => (
    <div className="field">
      <label htmlFor={`${id}-${key}`} className="field-label">
        {label}
      </label>
      <input
        id={`${id}-${key}`}
        className="short"
        type={type}
        min={type === "number" ? 1 : undefined}
        value={draft[key]}
        aria-invalid={Boolean(errors[key])}
        aria-describedby={`${id}-${key}-hint${errors[key] ? ` ${id}-${key}-err` : ""}`}
        onChange={(e) => set(key, e.target.value)}
      />
      <p id={`${id}-${key}-hint`} className="field-hint">
        {hint}
      </p>
      {errors[key] && (
        <p id={`${id}-${key}-err`} className="field-error">
          {errors[key]}
        </p>
      )}
    </div>
  );

  return (
    <form className="panel settings" onSubmit={onSubmit} noValidate aria-labelledby="settings-h">
      <h1 id="settings-h" className="page-title">
        Settings
      </h1>
      <section aria-labelledby="limits-h" className="settings-section">
        <h2 id="limits-h" className="panel-title">
          Safety limits
        </h2>
        <p className="muted">
          Tests above these limits are refused, both when they start and when the load is changed
          during a run. They stop a typo from sending far more traffic than you meant.
        </p>
        {field("maxVus", "Max virtual users", "Highest number of users a test can use.", "number")}
        {field("maxRate", "Max requests per second", "Highest arrival rate a test can use.", "number")}
        {field("maxDuration", "Max test length", "Total time including ramp-up, e.g. 30m or 2h.", "text")}
      </section>
      {saveError && (
        <p className="alert alert-error" role="alert">
          {saveError}
        </p>
      )}
      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={saving}>
          {saving ? "Saving…" : "Save limits"}
        </button>
        {saved && (
          <span className="save-ok" role="status">
            Saved.
          </span>
        )}
      </div>
    </form>
  );
}
