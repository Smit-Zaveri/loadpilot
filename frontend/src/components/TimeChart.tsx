import { useContext, useEffect, useRef } from "react";
import uPlot, { type AlignedData, type Options } from "uplot";
import "uplot/dist/uPlot.min.css";
import type { RunEvent } from "../api";
import { ThemeContext } from "../hooks/themeContext";
import { formatClock } from "../lib/format";

export interface ChartSeries {
  label: string;
  /** CSS custom property holding the colour, e.g. "--series-1". */
  colorVar: string;
  dash?: number[];
}

interface Props {
  title: string;
  data: AlignedData;
  series: ChartSeries[];
  events?: RunEvent[];
  /** Legend values (full precision). */
  formatValue: (v: number) => string;
  /** Y-axis tick labels; defaults to formatValue. */
  formatAxis?: (v: number) => string;
  height?: number;
}

/** When the cursor isn't on the chart, the legend shows the latest values. */
function showLatest(u: uPlot) {
  const n = u.data[0].length;
  if (n > 0 && u.cursor.idx == null) u.setLegend({ idx: n - 1 });
}

const EVENT_LABELS: Record<string, string> = {
  set_load: "load changed",
  pause: "paused",
  resume: "resumed",
  stop: "stop requested",
  abort: "aborted",
};

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function eventMarkers(getEvents: () => RunEvent[]): uPlot.Plugin {
  return {
    hooks: {
      draw: [
        (u) => {
          const events = getEvents();
          if (!events.length) return;
          const { ctx } = u;
          const { top, height } = u.bbox;
          ctx.save();
          ctx.strokeStyle = cssVar("--muted");
          ctx.fillStyle = cssVar("--muted");
          ctx.setLineDash([4, 4]);
          ctx.lineWidth = devicePixelRatio;
          ctx.font = `${11 * devicePixelRatio}px system-ui, sans-serif`;
          for (const ev of events) {
            const x = Math.round(u.valToPos(ev.time, "x", true));
            if (x < u.bbox.left || x > u.bbox.left + u.bbox.width) continue;
            ctx.beginPath();
            ctx.moveTo(x, top);
            ctx.lineTo(x, top + height);
            ctx.stroke();
            const label =
              ev.type === "set_load" && ev.value !== undefined
                ? `→ ${ev.value}`
                : (EVENT_LABELS[ev.type] ?? ev.type);
            ctx.fillText(label, x + 4 * devicePixelRatio, top + 12 * devicePixelRatio);
          }
          ctx.restore();
        },
      ],
    },
  };
}

export function TimeChart({
  title,
  data,
  series,
  events = [],
  formatValue,
  formatAxis = formatValue,
  height = 200,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  const eventsRef = useRef(events);
  const theme = useContext(ThemeContext);
  eventsRef.current = events;

  const seriesKey = series.map((s) => s.label + s.colorVar).join("|");

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const axis = {
      stroke: cssVar("--muted"),
      grid: { stroke: cssVar("--grid"), width: 1 },
      ticks: { stroke: cssVar("--grid"), width: 1 },
      font: "11px system-ui, sans-serif",
    };
    const opts: Options = {
      width: el.clientWidth || 400,
      height,
      cursor: { drag: { x: false, y: false } },
      legend: { live: true },
      scales: { x: { time: false }, y: { range: (_u, _min, max) => [0, max > 0 ? max * 1.1 : 1] } },
      axes: [
        { ...axis, values: (_u, vals) => vals.map((v) => formatClock(v)) },
        { ...axis, size: 64, values: (_u, vals) => vals.map((v) => formatAxis(v)) },
      ],
      series: [
        { label: "Time", value: (_u, v) => (v == null ? "–" : formatClock(v)) },
        ...series.map((s) => ({
          label: s.label,
          stroke: cssVar(s.colorVar),
          width: 2,
          dash: s.dash,
          points: { show: false },
          value: (_u: uPlot, v: number | null) => (v == null ? "–" : formatValue(v)),
        })),
      ],
      plugins: [eventMarkers(() => eventsRef.current)],
      hooks: {
        setCursor: [showLatest],
      },
    };
    const plot = new uPlot(opts, data, el);
    plotRef.current = plot;
    showLatest(plot);

    const ro = new ResizeObserver(() => plot.setSize({ width: el.clientWidth, height }));
    ro.observe(el);
    return () => {
      ro.disconnect();
      plot.destroy();
      plotRef.current = null;
    };
    // Recreate only when the series layout, theme or size changes; data updates below.
  }, [seriesKey, theme, height]);

  useEffect(() => {
    const plot = plotRef.current;
    if (!plot) return;
    plot.setData(data);
    showLatest(plot);
  }, [data]);

  return (
    <figure className="chart">
      <figcaption className="chart-title">{title}</figcaption>
      <div ref={wrapRef} className="chart-canvas" />
    </figure>
  );
}
