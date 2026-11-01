import { useCallback, useEffect, useId, useState } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError, api, isDone, type RunListItem } from "../api";
import { BaselineTag } from "../components/BaselineTag";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { StatusBadge } from "../components/StatusBadge";
import { formatClock, formatCount, formatMs, formatPercent, formatRate } from "../lib/format";

const PAGE_SIZE = 25;
const MAX_COMPARE = 4;

function formatDate(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function HistoryPage() {
  const navigate = useNavigate();
  const searchId = useId();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ items: RunListItem[]; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => {
      setDebounced(query.trim());
      setOffset(0);
    }, 250);
    return () => clearTimeout(t);
  }, [query]);

  const load = useCallback(() => {
    setError(null);
    return api
      .listRuns({ q: debounced, limit: PAGE_SIZE, offset })
      .then(setData)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : String(e)));
  }, [debounced, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = (id: string) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  async function deleteSelected() {
    setDeleting(true);
    const results = await Promise.allSettled(selected.map((id) => api.deleteRun(id)));
    const failed = results.filter((r) => r.status === "rejected").length;
    setDeleting(false);
    setConfirmDelete(false);
    setSelected([]);
    if (failed) setError(`${failed} run(s) couldn't be deleted. Stop running tests first.`);
    await load();
  }

  const canCompare = selected.length >= 2 && selected.length <= MAX_COMPARE;
  const finishedSelected = selected.length > 0;

  return (
    <div className="history">
      <div className="page-head">
        <h1 className="page-title">History</h1>
        <div className="toolbar">
          <button
            type="button"
            className="btn"
            disabled={!canCompare}
            onClick={() => navigate(`/compare?ids=${selected.join(",")}`)}
            title={`Select 2 to ${MAX_COMPARE} runs to compare`}
          >
            Compare selected{selected.length ? ` (${selected.length})` : ""}
          </button>
          <button
            type="button"
            className="btn btn-danger"
            disabled={!finishedSelected}
            onClick={() => setConfirmDelete(true)}
          >
            Delete selected
          </button>
        </div>
      </div>

      <div className="field search">
        <label htmlFor={searchId} className="field-label">
          Search by name
        </label>
        <input
          id={searchId}
          type="search"
          value={query}
          placeholder="checkout"
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      {selected.length > MAX_COMPARE && (
        <p className="field-hint">You can compare up to {MAX_COMPARE} runs at a time.</p>
      )}

      {error && (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      )}

      {data === null && !error ? (
        <p className="muted">Loading runs…</p>
      ) : data && data.total === 0 ? (
        <div className="panel empty-panel">
          {debounced ? (
            <p>No runs match “{debounced}”.</p>
          ) : (
            <>
              <p>No saved runs yet. Every test you start is saved here automatically.</p>
              <Link to="/" className="btn">
                Start a test
              </Link>
            </>
          )}
        </div>
      ) : data ? (
        <>
          <div className="panel table-panel">
            <div className="table-scroll">
              <table className="data-table history-table" aria-label="Saved runs">
                <thead>
                  <tr>
                    <th scope="col" className="col-check">
                      <span className="visually-hidden">Select</span>
                    </th>
                    <th scope="col">Name</th>
                    <th scope="col" className="col-optional">Started</th>
                    <th scope="col" className="col-optional">Duration</th>
                    <th scope="col" className="col-optional">Requests</th>
                    <th scope="col" className="col-optional">Req/s</th>
                    <th scope="col">p95</th>
                    <th scope="col">Failed</th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((r) => (
                    <tr key={r.id} className={selected.includes(r.id) ? "row-selected" : undefined}>
                      <td className="col-check">
                        <input
                          type="checkbox"
                          checked={selected.includes(r.id)}
                          disabled={!isDone(r.status)}
                          onChange={() => toggle(r.id)}
                          aria-label={`Select ${r.name}`}
                        />
                      </td>
                      <th scope="row">
                        <Link to={`/runs/${r.id}`} className="run-name-link">
                          {r.name}
                        </Link>
                        {r.is_baseline && <BaselineTag />}
                      </th>
                      <td className="col-optional">{formatDate(r.created_at)}</td>
                      <td className="col-optional">{formatClock(r.summary.duration || r.elapsed)}</td>
                      <td className="col-optional">{formatCount(r.summary.requests)}</td>
                      <td className="col-optional">{formatRate(r.summary.rps)}</td>
                      <td>{formatMs(r.summary.p95)}</td>
                      <td className={r.summary.error_rate > 0 ? "text-danger" : undefined}>
                        {formatPercent(r.summary.error_rate)}
                      </td>
                      <td>
                        <StatusBadge status={r.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="pager">
            <span className="muted num">
              {offset + 1}–{Math.min(offset + PAGE_SIZE, data.total)} of {formatCount(data.total)}
            </span>
            <button
              type="button"
              className="btn"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Newer
            </button>
            <button
              type="button"
              className="btn"
              disabled={offset + PAGE_SIZE >= data.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Older
            </button>
          </div>
        </>
      ) : null}

      <ConfirmDialog
        open={confirmDelete}
        title={`Delete ${selected.length} run${selected.length === 1 ? "" : "s"}?`}
        confirmLabel="Delete"
        danger
        busy={deleting}
        onConfirm={deleteSelected}
        onCancel={() => setConfirmDelete(false)}
      >
        <p>Their results and charts are removed for good.</p>
      </ConfirmDialog>
    </div>
  );
}
