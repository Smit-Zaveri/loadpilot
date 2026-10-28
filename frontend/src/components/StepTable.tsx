import type { StepSummary, Summary } from "../api";
import { formatCount, formatMs, formatPercent, formatRate } from "../lib/format";

function Row({ name, s, total }: { name: string; s: StepSummary; total?: boolean }) {
  const l = s.latency;
  return (
    <tr className={total ? "row-total" : undefined}>
      <th scope="row">{name}</th>
      <td>{formatCount(s.requests)}</td>
      <td>{formatRate(s.rps)}</td>
      <td className={s.failed > 0 ? "text-danger" : undefined}>{formatPercent(s.error_rate)}</td>
      <td>{formatMs(l.p50)}</td>
      <td>{formatMs(l.p90)}</td>
      <td>{formatMs(l.p95)}</td>
      <td>{formatMs(l.p99)}</td>
      <td>{formatMs(l.max)}</td>
    </tr>
  );
}

export function StepTable({ summary }: { summary: Summary }) {
  const steps = Object.entries(summary.steps);
  return (
    <div className="table-scroll">
      <table className="data-table" aria-label="Results per step">
        <thead>
          <tr>
            <th scope="col">Step</th>
            <th scope="col">Requests</th>
            <th scope="col">Req/s</th>
            <th scope="col">Failed</th>
            <th scope="col">p50</th>
            <th scope="col">p90</th>
            <th scope="col">p95</th>
            <th scope="col">p99</th>
            <th scope="col">Max</th>
          </tr>
        </thead>
        <tbody>
          {steps.map(([name, s]) => (
            <Row key={name} name={name} s={s} />
          ))}
          {steps.length > 1 && <Row name="All steps" s={summary} total />}
        </tbody>
      </table>
    </div>
  );
}
