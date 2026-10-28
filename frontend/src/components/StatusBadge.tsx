import type { RunStatus } from "../api";

const LABELS: Record<RunStatus, string> = {
  pending: "Starting",
  running: "Running",
  paused: "Paused",
  stopping: "Stopping",
  finished: "Finished",
  aborted: "Aborted",
  failed: "Failed",
};

/** Status is always spelled out; the dot only repeats it for quick scanning. */
export function StatusBadge({ status }: { status: RunStatus }) {
  return (
    <span className={`status status-${status}`}>
      <span className="status-dot" aria-hidden="true" />
      {LABELS[status]}
    </span>
  );
}
