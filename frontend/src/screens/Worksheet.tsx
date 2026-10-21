import { useEffect, useState } from "react";
import { api } from "../api";
import type { Verdict, WorksheetData, WorksheetItem } from "../types";

const VERDICT: Record<Verdict, string> = {
  strong: "Strong answer",
  good: "Good answer",
  partly: "Partly correct",
  needs_work: "Needs work",
  not_answered: "Not answered",
};

function Item({ n, q, selfTest, pending }: { n: number; q: WorksheetItem; selfTest: boolean; pending: boolean }) {
  const [revealed, setRevealed] = useState(false);
  const hidden = selfTest && !revealed;
  return (
    <section className="ws-item">
      <h3 className="ws-q"><span className="ws-num">{n}.</span> {q.question}</h3>
      {hidden ? (
        <button className="ws-reveal" onClick={() => setRevealed(true)}>Show my answer and the model answer</button>
      ) : (
        <dl className="ws-fields">
          <dt>Your answer</dt>
          <dd className="ws-quote">{q.answer || <span className="muted">No answer was given.</span>}</dd>
          {q.verdict && (
            <>
              <dt>Assessment</dt>
              <dd><span className={`ws-verdict v-${q.verdict}`}>{VERDICT[q.verdict]}</span> {q.assessment}</dd>
            </>
          )}
          {q.feedback && (
            <>
              <dt>Coach's feedback</dt>
              <dd>{q.feedback}</dd>
            </>
          )}
          {pending && !q.model_answer && (
            <>
              <dt>Model answer</dt>
              <dd className="muted ws-writing">Writing the model answer…</dd>
            </>
          )}
          {(q.model_answer || q.improved_answer) && !(pending && !q.model_answer) && (
            <>
              <dt>Model answer</dt>
              <dd className="ws-model">{q.model_answer || q.improved_answer}</dd>
            </>
          )}
          {q.key_points && q.key_points.length > 0 && (
            <>
              <dt>Key points to remember</dt>
              <dd><ul className="ws-points">{q.key_points.map((k) => <li key={k}>{k}</li>)}</ul></dd>
            </>
          )}
        </dl>
      )}
      <div className="ws-notes" aria-hidden="true"><span>Notes</span></div>
    </section>
  );
}

export default function WorksheetScreen({ id, onBack }: { id: string; onBack: () => void }) {
  const [data, setData] = useState<WorksheetData | null>(null);
  const [error, setError] = useState("");
  const [selfTest, setSelfTest] = useState(false);

  // Opens at once; while model answers are being written, ask again every 2 s.
  useEffect(() => {
    let stop = false;
    let timer = 0;
    const load = () =>
      api.worksheet(id)
        .then((d) => {
          if (stop) return;
          setData(d);
          if (d.pending) timer = window.setTimeout(load, 2000);
        })
        .catch((e) => !stop && setError((e as Error).message));
    void load();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [id]);

  if (error) return (<section><button className="quiet" onClick={onBack}>Back</button><p className="error-text">{error}</p></section>);
  if (!data) {
    return (
      <section className="ws-loading">
        <button className="quiet" onClick={onBack}>Back</button>
        <p className="note strong">Opening your worksheet…</p>
      </section>
    );
  }

  const s = data.session;
  const practice = data.items.filter((q) => q.phase === "practice");
  const interview = data.items.filter((q) => q.phase === "interview");
  const counts = data.items.reduce<Record<string, number>>((acc, q) => {
    if (q.verdict) acc[q.verdict] = (acc[q.verdict] || 0) + 1;
    return acc;
  }, {});
  const date = new Date(s.created_at * 1000);

  return (
    <section className="ws-wrap">
      <div className="ws-toolbar no-print">
        <button className="quiet" onClick={onBack}>Back to worksheets</button>
        <label className="check inline">
          <input type="checkbox" checked={selfTest} onChange={(e) => setSelfTest(e.target.checked)} />
          <span>Hide answers (test yourself)</span>
        </label>
        <button className="primary" onClick={() => window.print()}>Print / Save as PDF</button>
      </div>

      <article className="worksheet">
        <header className="ws-head">
          <p className="ws-kicker">AI Interview Coach</p>
          <h1>Interview Practice Worksheet</h1>
          <dl className="ws-meta">
            <div><dt>Interview</dt><dd>{s.interview_type || "Not stated"}</dd></div>
            <div><dt>Role</dt><dd>{s.role || "Not stated"}</dd></div>
            <div><dt>Level</dt><dd>{s.experience_level || "Not stated"}</dd></div>
            <div><dt>Date</dt><dd>{date.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })}</dd></div>
            <div><dt>Session</dt><dd>{s.kind === "practice" ? "Practice only" : "Practice and mock interview"}{s.minutes ? `, ${s.minutes} min` : ""}</dd></div>
            <div><dt>Mock interview score</dt><dd>{s.overall_score != null ? `${s.overall_score} / 100` : "Not taken"}</dd></div>
          </dl>
        </header>

        <section className="ws-howto">
          <h2>How to use this worksheet</h2>
          <ol>
            <li>Tick "Hide answers" and answer each question out loud, as if in the interview.</li>
            <li>Reveal your original answer and the model answer, and compare them.</li>
            <li>Learn the key points, not the exact words, so your answers sound natural.</li>
            <li>Practise the questions marked "Needs work" or "Not answered" first.</li>
          </ol>
        </section>

        {Object.keys(counts).length > 0 && (
          <section className="ws-glance">
            <h2>At a glance</h2>
            <p>
              {data.items.length} question{data.items.length === 1 ? "" : "s"}:{" "}
              {(Object.keys(VERDICT) as Verdict[]).filter((v) => counts[v]).map((v, i) => (
                <span key={v}>{i > 0 ? ", " : ""}<span className={`ws-verdict v-${v}`}>{counts[v]} {VERDICT[v].toLowerCase()}</span></span>
              ))}
            </p>
          </section>
        )}

        {data.pending && (
          <p className="note strong no-print" role="status">
            Writing model answers and assessments… they appear here in a few seconds.
          </p>
        )}
        {data.error && (
          <p className="note strong no-print">
            Model answers could not be written right now ({data.error}). Your questions and answers are shown below;
            open the worksheet again later to add the model answers.
          </p>
        )}

        {practice.length > 0 && (
          <section className="ws-part">
            <h2>Part A: Practice questions</h2>
            {practice.map((q, i) => <Item key={`p${i}`} n={i + 1} q={q} selfTest={selfTest} pending={!!data.pending} />)}
          </section>
        )}
        {interview.length > 0 && (
          <section className="ws-part">
            <h2>{practice.length > 0 ? "Part B: " : ""}Mock interview questions</h2>
            {interview.map((q, i) => <Item key={`i${i}`} n={i + 1} q={q} selfTest={selfTest} pending={!!data.pending} />)}
          </section>
        )}
        {data.items.length === 0 && <p className="muted">No questions were asked in this session.</p>}

        <footer className="ws-foot">
          Prepared on {new Date().toLocaleDateString()} by AI Interview Coach. Model answers and assessments are written by
          AI as study guidance; check important facts before relying on them.
        </footer>
      </article>
    </section>
  );
}
