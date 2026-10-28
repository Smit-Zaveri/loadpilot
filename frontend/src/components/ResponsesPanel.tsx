import type { Summary } from "../api";
import { formatCount, formatPercent } from "../lib/format";

function codeClass(code: string): string {
  if (code === "429") return "code-limited";
  if (code.startsWith("5") || code.startsWith("4")) return "code-bad";
  return "code-ok";
}

export function ResponsesPanel({ summary }: { summary: Summary }) {
  const codes = Object.entries(summary.status).sort(([a], [b]) => a.localeCompare(b));
  const errors = Object.entries(summary.errors).sort(([, a], [, b]) => b.count - a.count);
  const total = summary.requests;

  return (
    <div className="responses">
      <section aria-labelledby="codes-h">
        <h3 id="codes-h" className="panel-h">Status codes</h3>
        {codes.length === 0 ? (
          <p className="muted">No responses yet.</p>
        ) : (
          <ul className="code-list">
            {codes.map(([code, n]) => (
              <li key={code} className={codeClass(code)}>
                <span className="code">{code}</span>
                <span className="num">{formatCount(n)}</span>
                <span className="num muted">{formatPercent(total ? n / total : 0)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="errors-h">
        <h3 id="errors-h" className="panel-h">Connection errors</h3>
        {errors.length === 0 ? (
          <p className="muted">None. Every request got an HTTP response.</p>
        ) : (
          <ul className="error-list">
            {errors.map(([kind, info]) => (
              <li key={kind}>
                <div className="error-head">
                  <span className="text-danger">{kind}</span>
                  <span className="num">{formatCount(info.count)}</span>
                </div>
                {info.sample && <code className="error-sample">{info.sample}</code>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
