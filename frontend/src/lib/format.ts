export function formatMs(ms: number): string {
  if (!Number.isFinite(ms)) return "–";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  if (ms >= 100) return `${ms.toFixed(0)} ms`;
  if (ms >= 1) return `${ms.toFixed(1)} ms`;
  return `${ms.toFixed(2)} ms`;
}

/** Compact tick labels: "0", "50 ms", "1.5 s". */
export function formatAxisMs(ms: number): string {
  if (ms === 0) return "0";
  if (ms >= 1000) return `${+(ms / 1000).toFixed(2)} s`;
  return `${+ms.toFixed(ms < 10 ? 1 : 0)} ms`;
}

/** Tick labels for a percentage axis, trimming trailing zeros: "0%", "0.25%", "12%". */
export function formatAxisPercent(pct: number): string {
  return `${+pct.toFixed(pct < 1 ? 2 : pct < 10 ? 1 : 0)}%`;
}

/** Tick labels for counts and rates: "0", "2.5", "50", "1,200". */
export function formatAxisNumber(n: number): string {
  return Number.isInteger(n) ? formatCount(n) : `${+n.toFixed(2)}`;
}

export function formatCount(n: number): string {
  return Math.round(n).toLocaleString("en-US");
}

export function formatRate(n: number): string {
  return n >= 100 ? formatCount(n) : n.toFixed(1);
}

export function formatPercent(ratio: number): string {
  const pct = ratio * 100;
  if (pct === 0) return "0%";
  if (pct < 0.01) return "<0.01%";
  return `${pct < 10 ? pct.toFixed(2) : pct.toFixed(1)}%`;
}

/** 65 -> "1:05", 3725 -> "1:02:05" */
export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export function formatTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
