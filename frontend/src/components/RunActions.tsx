import { useEffect, useId, useState } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError, api, type RunDetail } from "../api";
import { ConfirmDialog } from "./ConfirmDialog";

interface Props {
  run: RunDetail;
  onChange: (run: RunDetail) => void;
}

/** Actions for a finished run: re-run, baseline, compare, notes, delete. */
export function RunActions({ run, onChange }: Props) {
  const navigate = useNavigate();
  const notesId = useId();
  const [baselineId, setBaselineId] = useState<string | null>(null);
  const [notes, setNotes] = useState(run.notes);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notesSaved, setNotesSaved] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    // Find the baseline for this test name (if it's another run) to offer a comparison.
    let cancelled = false;
    api
      .listRuns({ q: run.name, limit: 100 })
      .then((page) => {
        if (cancelled) return;
        const base = page.items.find((r) => r.name === run.name && r.is_baseline);
        setBaselineId(base && base.id !== run.id ? base.id : null);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [run.name, run.id, run.is_baseline]);

  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const toggleBaseline = () =>
    act(async () => {
      await api.setBaseline(run.id, !run.is_baseline);
      onChange({ ...run, is_baseline: !run.is_baseline });
    });

  const saveNotes = () =>
    act(async () => {
      await api.updateRun(run.id, { notes });
      onChange({ ...run, notes });
      setNotesSaved(true);
    });

  const remove = () =>
    act(async () => {
      await api.deleteRun(run.id);
      navigate("/history");
    });

  return (
    <section className="panel run-actions" aria-label="Run actions">
      <div className="action-row">
        <button type="button" className="btn btn-primary" onClick={() => navigate("/", { state: { plan: run.plan } })}>
          Run again
        </button>
        <button
          type="button"
          className="btn"
          aria-pressed={run.is_baseline}
          disabled={busy}
          onClick={toggleBaseline}
          title="The baseline is the reference run for this test name"
        >
          {run.is_baseline ? "Remove as baseline" : "Mark as baseline"}
        </button>
        {baselineId && (
          <Link to={`/compare?ids=${baselineId},${run.id}`} className="btn">
            Compare with baseline
          </Link>
        )}
        <button type="button" className="btn btn-danger" disabled={busy} onClick={() => setConfirmDelete(true)}>
          Delete
        </button>
      </div>
      <div className="field notes">
        <label htmlFor={notesId} className="field-label">
          Notes
        </label>
        <textarea
          id={notesId}
          rows={2}
          value={notes}
          placeholder="What changed before this run? e.g. added a cache, new instance size"
          onChange={(e) => {
            setNotes(e.target.value);
            setNotesSaved(false);
          }}
        />
        <div className="form-actions">
          <button type="button" className="btn" disabled={busy || notes === run.notes} onClick={saveNotes}>
            Save notes
          </button>
          {notesSaved && notes === run.notes && (
            <span className="save-ok" role="status">
              Saved.
            </span>
          )}
        </div>
      </div>
      {error && (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      )}
      <ConfirmDialog
        open={confirmDelete}
        title="Delete this run?"
        confirmLabel="Delete run"
        danger
        busy={busy}
        onConfirm={remove}
        onCancel={() => setConfirmDelete(false)}
      >
        <p>“{run.name}” and its charts are removed for good.</p>
      </ConfirmDialog>
    </section>
  );
}
