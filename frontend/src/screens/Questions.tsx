import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { QuestionSession } from "../types";

/** Worksheets page: one formal worksheet per saved session. */
export default function WorksheetsScreen({ onOpen }: { onOpen: (id: string) => void }) {
  const [sessions, setSessions] = useState<QuestionSession[] | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    api.questions().then((d) => setSessions(d.sessions)).catch((e) => setError((e as Error).message));
  }, []);

  const term = search.trim().toLowerCase();
  const shown = useMemo(
    () => (sessions || []).filter((s) => !term || s.questions.some((q) => q.question.toLowerCase().includes(term))),
    [sessions, term],
  );

  return (
    <section className="questions-page">
      <h1>Worksheets</h1>
      <p className="muted">
        Every saved session becomes a worksheet: the questions you were asked, your answers, an assessment, a model
        answer and key points to remember. Open one to revise, test yourself, or print it.
      </p>
      <div className="q-tools">
        <input type="search" placeholder="Find a question" value={search} onChange={(e) => setSearch(e.target.value)}
          aria-label="Find a question in your worksheets" />
      </div>

      {error && <p className="error-text">{error}</p>}
      {!sessions && !error && <p className="muted">Loading…</p>}
      {sessions && sessions.length === 0 && (
        <p className="empty">
          No worksheets yet. Tick "Save my interview report" on the start screen; every saved session, even one where
          you only practise, becomes a worksheet here.
        </p>
      )}
      {sessions && sessions.length > 0 && shown.length === 0 && <p className="muted">No worksheet has a question like that.</p>}

      <div className="ws-list">
        {shown.map((s) => {
          const p = s.questions.filter((q) => q.phase === "practice").length;
          const i = s.questions.length - p;
          const matches = term ? s.questions.filter((q) => q.question.toLowerCase().includes(term)) : [];
          return (
            <article key={s.id} className="ws-card card">
              <div>
                <h2>{s.interview_type || "Session"}{s.role ? `, ${s.role}` : ""}</h2>
                <p className="muted">
                  {new Date(s.created_at * 1000).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })}
                  {" · "}{p} practice question{p === 1 ? "" : "s"}{i ? `, ${i} interview question${i === 1 ? "" : "s"}` : ""}
                  {s.overall_score != null ? ` · score ${s.overall_score}/100` : ""}
                </p>
                {matches.slice(0, 2).map((q) => <p key={q.question} className="ws-match">“{q.question}”</p>)}
              </div>
              <button className="primary" onClick={() => onOpen(s.id)}>Open worksheet</button>
            </article>
          );
        })}
      </div>
    </section>
  );
}
