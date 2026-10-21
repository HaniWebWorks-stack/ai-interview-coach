import { useEffect, useState } from "react";
import { api } from "../api";
import type { Focus, ProgressData } from "../types";
import { ActivityBars, CriterionBars, LineChart } from "../components/Charts";
import { downloadCsv } from "../download";

export default function ProgressScreen({ onPractice, onStudio, onOpenWorksheet }: {
  onPractice: (f: Focus) => void;
  onStudio: () => void;
  onOpenWorksheet: (id: string) => void;
}) {
  const [data, setData] = useState<ProgressData | null>(null);
  const [error, setError] = useState("");
  const [category, setCategory] = useState("");
  const [role, setRole] = useState("");

  useEffect(() => {
    setError("");
    api.progress(category, role).then(setData).catch((e) => setError((e as Error).message));
  }, [category, role]);

  if (error) return <section><h1>Progress</h1><p className="error-text" role="alert">{error}</p></section>;
  if (!data) return <section><h1>Progress</h1><div className="skeleton" role="status"><span className="sk-bar" /><span className="sk-bar short" /><p className="muted">Loading your history…</p></div></section>;

  const empty = data.totals.sessions === 0;
  const exportTracker = () => downloadCsv("interview-progress.csv",
    ["Date", "Type", "Session", "Category", "Score (AI estimate)", "Targeted topic"],
    data.timeline.map((t) => [t.date, t.kind, t.title, t.category, t.score ?? "", t.focus]));

  return (
    <section className="progress">
      <div className="page-head">
        <div>
          <h1>Progress</h1>
          <p className="muted">Calculated only from your saved sessions on this laptop. Scores are AI estimates for practice, and
            interviews are only compared with interviews of the same type.</p>
        </div>
        {!empty && <button onClick={exportTracker}>Download progress tracker (CSV)</button>}
      </div>

      {empty ? (
        <p className="empty">No saved sessions yet. Tick "Save my interview report" before you practise; your progress appears here after your first saved session, and trends after two mock interviews of the same type.</p>
      ) : (
        <>
          <div className="filters" role="group" aria-label="Filters">
            <label>Interview type
              <select value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="">All types</option>
                {data.filters.categories.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </label>
            {data.filters.roles.length > 1 && (
              <label>Role
                <select value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="">All roles</option>
                  {data.filters.roles.map((r) => <option key={r}>{r}</option>)}
                </select>
              </label>
            )}
          </div>

          <div className="tiles">
            <div className="tile"><span className="tile-num">{data.totals.sessions}</span><span>saved sessions</span></div>
            <div className="tile"><span className="tile-num">{data.totals.interviews}</span><span>scored mock interviews</span></div>
            <div className="tile"><span className="tile-num">{data.totals.practice}</span><span>practice sessions</span></div>
          </div>

          {data.categories.length === 0 && <p className="note">No scored mock interviews match these filters yet. Practice sessions are listed in the timeline below.</p>}

          {data.categories.map((c) => (
            <section key={c.category} className="card cat">
              <h2>{c.label}</h2>
              {c.trend.enough_data ? (
                <p className="lead-sm">
                  {c.trend.count} interviews. Overall score {c.trend.first} → {c.trend.latest}
                  {" "}({(c.trend.change ?? 0) >= 0 ? "+" : ""}{c.trend.change}), average {c.trend.average}.
                </p>
              ) : (
                <p className="note">One {c.label.toLowerCase()} so far (score {c.trend.latest}). Do at least one more of this type to see a trend; one result is not a trend.</p>
              )}
              <div className="cat-charts">
                {c.sessions.length >= 2 && (
                  <LineChart title="Overall score over time" yMax={100} yLabel="Score"
                    points={c.sessions.map((s) => ({ x: s.date, y: s.score, label: `${s.date} · ${s.interview_type}${s.role ? `, ${s.role}` : ""}` }))} />
                )}
                {c.criteria.length > 0 && (
                  <CriterionBars title="Criteria: latest score and your average (1 to 5)"
                    rows={c.criteria.map((x) => ({ name: x.name, latest: x.latest, average: x.average, assessed: x.assessed }))} />
                )}
              </div>
              <div className="cat-lists">
                <div>
                  <h3>Repeated weak spots</h3>
                  {c.repeated_weaknesses.length ? (
                    <ul className="plain">{c.repeated_weaknesses.map((w) => (
                      <li key={w.name}><b>{w.name}</b> <span className="small muted">weak in {w.times_weak} of {w.assessed} interviews</span>
                        <button className="small" onClick={() => onPractice({ topic: w.name, kind: "weakness", interview_type: c.label })}>Practise</button></li>
                    ))}</ul>
                  ) : <p className="muted small">None repeated so far.</p>}
                </div>
                <div>
                  <h3>Consistent strengths</h3>
                  {c.strengths.length ? (
                    <ul className="plain">{c.strengths.map((s) => <li key={s.name}>✓ <b>{s.name}</b> <span className="small muted">average {s.average} over {s.assessed}</span></li>)}</ul>
                  ) : <p className="muted small">{c.trend.enough_data ? "None consistent yet." : "Needs two or more interviews."}</p>}
                </div>
                <div>
                  <h3>Improved</h3>
                  {c.improved.length ? (
                    <ul className="plain">{c.improved.map((s) => <li key={s.name}>▲ <b>{s.name}</b> <span className="small muted">{s.from} → {s.to}</span></li>)}</ul>
                  ) : <p className="muted small">{c.trend.enough_data ? "No clear improvement yet." : "Needs two or more interviews."}</p>}
                </div>
                <div>
                  <h3>Reassess next</h3>
                  {c.needs_reassessment.length ? (
                    <ul className="plain">{c.needs_reassessment.map((s) => (
                      <li key={s.name}><b>{s.name}</b> <span className="small muted">{s.reason}</span>
                        <button className="small" onClick={() => onPractice({ topic: s.name, kind: "reassess", interview_type: c.label })}>Reassess</button></li>
                    ))}</ul>
                  ) : <p className="muted small">Nothing waiting.</p>}
                </div>
              </div>
            </section>
          ))}

          {data.activity.length > 0 && <section className="card"><ActivityBars weeks={data.activity} /></section>}

          <section className="card">
            <div className="sec-head">
              <h2>Learning timeline</h2>
              <button onClick={onStudio}>Open the Preparation Studio</button>
            </div>
            <ol className="timeline">
              {data.timeline.map((t) => (
                <li key={t.id} className={`tl-${t.kind}`}>
                  <span className="tl-dot" aria-hidden="true">{t.kind === "interview" ? "●" : "○"}</span>
                  <span className="tl-date">{t.date}</span>
                  <span className="tl-body">
                    <b>{t.kind === "interview" ? "Mock interview" : "Practice"}</b>: {t.title}
                    {t.focus && <span className="tag subtle">Targeted: {t.focus}</span>}
                    {t.score != null && <span className="tag">{t.score}/100</span>}
                  </span>
                  <button className="link" onClick={() => onOpenWorksheet(t.id)}>Worksheet</button>
                </li>
              ))}
            </ol>
          </section>
        </>
      )}
    </section>
  );
}
