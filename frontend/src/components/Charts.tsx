import { useMemo, useRef, useState } from "react";

/*
 * Small SVG charts drawn from real saved data (no chart library).
 * Colours: validated categorical slots 1-2 (see styles.css --series-*),
 * a table view for every chart, tooltips that enhance but never gate.
 */

interface Point { x: string; y: number; label?: string }

function useTip() {
  const [tip, setTip] = useState<{ x: number; y: number; lines: string[] } | null>(null);
  return { tip, setTip };
}

function Tip({ tip }: { tip: { x: number; y: number; lines: string[] } | null }) {
  if (!tip) return null;
  return (
    <div className="ch-tip" style={{ left: tip.x, top: tip.y }} role="status">
      <strong>{tip.lines[0]}</strong>
      {tip.lines.slice(1).map((l) => <span key={l}>{l}</span>)}
    </div>
  );
}

function TableToggle({ caption, head, rows }: { caption: string; head: string[]; rows: (string | number)[][] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="ch-table-wrap">
      <button className="link" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide table" : "Show as table"}</button>
      {open && (
        <table className="ch-table">
          <caption className="sr">{caption}</caption>
          <thead><tr>{head.map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
          <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
        </table>
      )}
    </div>
  );
}

/** One series over time (e.g. overall score). Crosshair + tooltip snaps to the nearest point. */
export function LineChart({ points, yMax, yLabel, title }: { points: Point[]; yMax: number; yLabel: string; title: string }) {
  const W = 640, H = 220, L = 40, R = 16, T = 14, B = 34;
  const ref = useRef<HTMLDivElement>(null);
  const { tip, setTip } = useTip();
  const [hover, setHover] = useState<number | null>(null);
  const xs = points.map((_, i) => (points.length === 1 ? L + (W - L - R) / 2 : L + (i * (W - L - R)) / (points.length - 1)));
  const y = (v: number) => T + (H - T - B) * (1 - v / yMax);
  const ticks = yMax === 100 ? [0, 25, 50, 75, 100] : [0, 1, 2, 3, 4, 5];
  const move = (clientX: number) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box || !points.length) return;
    const sx = ((clientX - box.left) / box.width) * W;
    let best = 0;
    xs.forEach((x, i) => { if (Math.abs(x - sx) < Math.abs(xs[best] - sx)) best = i; });
    setHover(best);
    const p = points[best];
    setTip({ x: (xs[best] / W) * box.width, y: (y(p.y) / H) * box.height - 8, lines: [`${p.y}${yMax === 100 ? " / 100" : " / 5"}`, p.label || p.x] });
  };
  return (
    <figure className="ch">
      <figcaption>{title}</figcaption>
      <div className="ch-box" ref={ref} onPointerMove={(e) => move(e.clientX)} onPointerLeave={() => { setHover(null); setTip(null); }}>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}: ${points.map((p) => `${p.x} ${p.y}`).join(", ")}`}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} className="ch-grid" />
              <text x={L - 8} y={y(t) + 4} className="ch-axis" textAnchor="end">{t}</text>
            </g>
          ))}
          {points.map((p, i) => (
            <text key={p.x + i} x={xs[i]} y={H - 10} className="ch-axis" textAnchor="middle">
              {points.length > 8 && i % Math.ceil(points.length / 8) ? "" : p.x.slice(5)}
            </text>
          ))}
          {hover !== null && <line x1={xs[hover]} x2={xs[hover]} y1={T} y2={H - B} className="ch-cross" />}
          {points.length > 1 && (
            <polyline className="ch-line" points={points.map((p, i) => `${xs[i]},${y(p.y)}`).join(" ")} />
          )}
          {points.map((p, i) => (
            <circle key={i} cx={xs[i]} cy={y(p.y)} r={hover === i ? 6 : 4.5} className="ch-dot" tabIndex={0}
              aria-label={`${p.label || p.x}: ${p.y}`}
              onFocus={() => { setHover(i); setTip({ x: (xs[i] / W) * (ref.current?.clientWidth || W), y: (y(p.y) / H) * (ref.current?.clientHeight || H) - 8, lines: [`${p.y}`, p.label || p.x] }); }}
              onBlur={() => { setHover(null); setTip(null); }} />
          ))}
          {points.length > 0 && (
            <text x={xs[xs.length - 1]} y={y(points[points.length - 1].y) - 12} className="ch-direct" textAnchor="middle">
              {points[points.length - 1].y}
            </text>
          )}
          <text x={12} y={T + 4} className="ch-axis" transform={`rotate(-90 12 ${T + 60})`} textAnchor="middle">{yLabel}</text>
        </svg>
        <Tip tip={tip} />
      </div>
      <TableToggle caption={title} head={["Date", yLabel]} rows={points.map((p) => [p.label || p.x, p.y])} />
    </figure>
  );
}

/** Criterion comparison: bar = latest score, tick = average over all interviews (1-5). */
export function CriterionBars({ rows, title }: { rows: { name: string; latest: number; average: number; assessed: number }[]; title: string }) {
  const { tip, setTip } = useTip();
  const ref = useRef<HTMLDivElement>(null);
  return (
    <figure className="ch">
      <figcaption>{title}</figcaption>
      <ul className="ch-legend" aria-label="Legend">
        <li><span className="sw sw-1" aria-hidden="true" />Latest score</li>
        <li><span className="sw sw-tick" aria-hidden="true" />Your average</li>
      </ul>
      <div className="ch-bars" ref={ref}>
        {rows.map((r) => (
          <div key={r.name} className="ch-bar-row" tabIndex={0}
            onPointerMove={(e) => {
              const b = ref.current?.getBoundingClientRect();
              if (b) setTip({ x: e.clientX - b.left, y: e.clientY - b.top - 12, lines: [`${r.latest} / 5 latest`, `${r.name}`, `average ${r.average} over ${r.assessed} interview${r.assessed === 1 ? "" : "s"}`] });
            }}
            onPointerLeave={() => setTip(null)}
            onFocus={(e) => setTip({ x: e.currentTarget.offsetLeft + 160, y: e.currentTarget.offsetTop - 12, lines: [`${r.latest} / 5 latest`, r.name, `average ${r.average}`] })}
            onBlur={() => setTip(null)}
            aria-label={`${r.name}: latest ${r.latest} of 5, average ${r.average}`}>
            <span className="ch-bar-name">{r.name}</span>
            <span className="ch-bar-track">
              <span className="ch-bar-fill" style={{ width: `${(r.latest / 5) * 100}%` }} />
              <span className="ch-bar-avg" style={{ left: `${(r.average / 5) * 100}%` }} />
            </span>
            <span className="ch-bar-val">{r.latest}</span>
          </div>
        ))}
        <Tip tip={tip} />
      </div>
      <TableToggle caption={title} head={["Criterion", "Latest", "Average", "Interviews"]}
        rows={rows.map((r) => [r.name, r.latest, r.average, r.assessed])} />
    </figure>
  );
}

/** Weekly activity: two series stacked (mock interviews, practice sessions). */
export function ActivityBars({ weeks }: { weeks: { week: string; interviews: number; practice: number }[] }) {
  const max = Math.max(1, ...weeks.map((w) => w.interviews + w.practice));
  const { tip, setTip } = useTip();
  const ref = useRef<HTMLDivElement>(null);
  const shown = useMemo(() => weeks.slice(-12), [weeks]);
  return (
    <figure className="ch">
      <figcaption>Practice activity per week</figcaption>
      <ul className="ch-legend" aria-label="Legend">
        <li><span className="sw sw-1" aria-hidden="true" />Mock interviews</li>
        <li><span className="sw sw-2" aria-hidden="true" />Practice sessions</li>
      </ul>
      <div className="ch-cols" ref={ref}>
        {shown.map((w) => (
          <div key={w.week} className="ch-col" tabIndex={0}
            aria-label={`Week of ${w.week}: ${w.interviews} mock interviews, ${w.practice} practice sessions`}
            onPointerMove={(e) => {
              const b = ref.current?.getBoundingClientRect();
              if (b) setTip({ x: e.clientX - b.left, y: e.clientY - b.top - 12, lines: [`${w.interviews + w.practice} sessions`, `Week of ${w.week}`, `${w.interviews} interviews, ${w.practice} practice`] });
            }}
            onPointerLeave={() => setTip(null)}>
            <span className="ch-stack">
              {w.practice > 0 && <span className="ch-seg seg-2" style={{ height: `${(w.practice / max) * 100}%` }} />}
              {w.interviews > 0 && <span className="ch-seg seg-1" style={{ height: `${(w.interviews / max) * 100}%` }} />}
            </span>
            <span className="ch-col-label">{w.week.slice(5)}</span>
          </div>
        ))}
        <Tip tip={tip} />
      </div>
      <TableToggle caption="Practice activity per week" head={["Week of", "Mock interviews", "Practice sessions"]}
        rows={shown.map((w) => [w.week, w.interviews, w.practice])} />
    </figure>
  );
}
