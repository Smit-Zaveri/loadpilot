import type { RunDetail, StreamMessage } from "../api";

/** Applies one WebSocket message to the run. Pure, so it's easy to test. */
export function applyMessage(run: RunDetail | null, msg: StreamMessage): RunDetail | null {
  switch (msg.type) {
    case "snapshot":
    case "finished":
      return msg.run;
    case "point": {
      if (!run) return run;
      const last = run.series.at(-1);
      // The snapshot and the live stream can overlap by a point; skip duplicates.
      const isNew = !last || msg.point.t > last.t;
      return {
        ...run,
        status: msg.status,
        elapsed: msg.elapsed,
        target: msg.point.target,
        summary: msg.summary,
        series: isNew ? [...run.series, msg.point] : run.series,
        events: isNew && msg.point.events.length ? [...run.events, ...msg.point.events] : run.events,
      };
    }
    case "status":
      return run ? { ...run, status: msg.status, target: msg.target } : run;
  }
}
