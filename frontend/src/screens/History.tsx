import { useEffect, useState } from "react";
import { api } from "../api";
import type { HistoryItem, Report } from "../types";
import { ReportView, type ReportActions } from "./Results";
import QuestionList from "../QuestionList";

export default function HistoryScreen({ onOpenWorksheet, actions }: { onOpenWorksheet: (id: string) => void; actions?: ReportActions }) {
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [where, setWhere] = useState("");
  const [open, setOpen] = useState<{ id: string; report: Report; transcript: { role: string; text: string }[] } | null>(null);
  const [error, setError] = useState("");
  const [confirmAll, setConfirmAll] = useState(false);
  const [confirmOne, setConfirmOne] = useState<string | null>(null);

  const load = () =>
    api.history()
      .then((d) => { setItems(d.sessions); setWhere(d.stored_at); })
      .catch((e) => setError((e as Error).message));

  useEffect(() => { void load(); }, []);

  const remove = async (id: string) => {
    await api.deleteHistory(id);
    setOpen(null);
    void load();
  };

  if (open) {
    return (
      <section>
        <button className="quiet" onClick={() => setOpen(null)}>Back to history</button>
        {open.report.kind === "practice" ? (
          <div className="card">
            <h2>Practice session</h2>
            <p className="muted">No mock interview in this session, so there is no score. Here are the questions you practised.</p>
            <QuestionList items={open.report.question_log || []} openFirst />
          </div>
        ) : (
          <>
            <ReportView report={{ ...open.report, saved: true, session_id: open.report.session_id || open.id }} actions={actions} />
            {open.report.question_log && open.report.question_log.length > 0 && (
              <section className="card all-questions">
                <h2>All questions from this session</h2>
                <QuestionList items={open.report.question_log} />
              </section>
            )}
          </>
        )}
        <details className="card">
          <summary>Interview transcript</summary>
          {open.transcript.map((l, i) => (
            <p key={i} className={`line ${l.role}`}><span className="who">{l.role === "user" ? "You" : "Interviewer"}</span>{l.text}</p>
          ))}
        </details>
      </section>
    );
  }

  return (
    <section className="history">
      <h1>History</h1>
      <p className="muted">
        Reports you chose to save. They are stored only on this laptop ({where || "…"}), never online.
      </p>
      {error && <p className="error-text">{error}</p>}
      {items && items.length === 0 && (
        <p className="empty">No saved reports yet. Tick "Save my interview report" before starting a session to keep one here.</p>
      )}
      {items && items.length > 0 && (
        <>
          <table className="history-table">
            <thead>
              <tr><th>Date</th><th>Interview</th><th>Score</th><th>Length</th><th><span className="sr">Actions</span></th></tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id}>
                  <td>{new Date(it.created_at * 1000).toLocaleString()}</td>
                  <td>{it.interview_type}{it.role ? `, ${it.role}` : ""}</td>
                  <td>{it.overall_score ?? "Practice"}</td>
                  <td>{it.minutes} min</td>
                  <td className="row-actions">
                    <button onClick={() => api.historyItem(it.id).then((d) => setOpen({ id: it.id, report: d.report, transcript: d.transcript }))}>Open</button>
                    <button onClick={() => onOpenWorksheet(it.id)}>Worksheet</button>
                    {confirmOne === it.id ? (
                      <span className="confirm small">Delete?
                        <button className="danger" onClick={() => { setConfirmOne(null); void remove(it.id); }}>Delete</button>
                        <button onClick={() => setConfirmOne(null)}>Keep</button>
                      </span>
                    ) : (
                      <button className="danger-text" onClick={() => setConfirmOne(it.id)}>Delete</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!confirmAll ? (
            <button className="danger-text" onClick={() => setConfirmAll(true)}>Delete all saved reports</button>
          ) : (
            <span className="confirm">
              Delete all {items.length} saved reports? This cannot be undone.
              <button className="danger" onClick={() => api.deleteAllHistory().then(() => { setConfirmAll(false); void load(); })}>Delete all</button>
              <button onClick={() => setConfirmAll(false)}>Cancel</button>
            </span>
          )}
        </>
      )}
    </section>
  );
}
