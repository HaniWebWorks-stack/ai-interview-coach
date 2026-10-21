import QuestionList from "../QuestionList";
import type { Focus, Report } from "../types";
import { downloadCsv, slug } from "../download";

export interface ReportActions {
  onPractice: (f: Focus) => void;
  onStudio: (req: { type: "diagram" | "studypack"; topic: string; kind?: "concept" | "mindmap" | "star" }) => void;
  onAsk: (ctx: { type: "report"; id: string; label: string }) => void;
}

const CONFIDENCE: Record<string, string> = {
  high: "High confidence: plenty of answers to judge",
  medium: "Medium confidence: a normal short interview",
  low: "Low confidence: very few answers, treat scores as rough",
};

function Score({ value, max = 5 }: { value: number; max?: number }) {
  if (!value) return <span className="score na">Not enough evidence</span>;
  return (
    <span className="score" aria-label={`${value} out of ${max}`}>
      <span className="track"><span className="fill" style={{ width: `${(value / max) * 100}%` }} /></span>
      <span className="num">{value}/{max}</span>
    </span>
  );
}

export function ReportView({ report, actions }: { report: Report; actions?: ReportActions }) {
  if (report.error) {
    return (
      <div className="card">
        <h2>{report.error_kind === "empty" ? "Nothing to score yet" : "The report could not be created"}</h2>
        <p>{report.error}</p>
        {report.error_kind !== "empty" && (
          <p className="muted">Your interview itself worked. This usually means Google's free tier was busy. Try another interview later.</p>
        )}
      </div>
    );
  }
  const p = report.profile;
  return (
    <div className="report">
      <header className="report-head">
        <div className="overall" aria-label={`Overall score ${report.overall_score} out of 100`}>
          <span className="overall-num">{report.overall_score}</span>
          <span className="overall-of">out of 100</span>
        </div>
        <div>
          <h1>{p?.interview_type || "Mock interview"}{p?.role ? `, ${p.role}` : ""}</h1>
          <p className="muted">
            {report.category_label}{report.minutes != null ? `, ${report.minutes} minutes` : ""}
            {report.end_reason ? `, ${report.end_reason}` : ""}
          </p>
          <p className="summary">{report.overall_summary}</p>
        </div>
      </header>

      <section className="card glance">
        <h2>At a glance</h2>
        <p className="small muted">
          AI estimate for practice, not an official or validated measurement. {CONFIDENCE[report.confidence || "medium"]}.
        </p>
        {report.areas_to_improve.length > 0 && (
          <>
            <h3>Your top priorities</h3>
            <ol className="priorities">
              {report.areas_to_improve.slice(0, 3).map((a) => (
                <li key={a}>
                  <span>{a}</span>
                  {actions && (
                    <span className="row-actions">
                      <button className="small" onClick={() => actions.onPractice({
                        topic: a.slice(0, 120), kind: "weakness", interview_type: p?.interview_type, role: p?.role, level: p?.experience_level,
                      })}>Practise this</button>
                      <button className="small" onClick={() => actions.onStudio({ type: "diagram", topic: a.slice(0, 120), kind: "concept" })}>Explain with a diagram</button>
                    </span>
                  )}
                </li>
              ))}
            </ol>
          </>
        )}
        <div className="row-actions wrap no-print">
          {actions && report.saved && report.session_id && (
            <button onClick={() => actions.onAsk({ type: "report", id: report.session_id!, label: "this interview report" })}>Ask about my feedback</button>
          )}
          {actions && report.areas_to_improve[0] && (
            <button onClick={() => actions.onStudio({ type: "studypack", topic: report.areas_to_improve[0].slice(0, 120) })}>Make a study pack for my top priority</button>
          )}
          <button onClick={() => window.print()}>Print / Save as PDF</button>
          <button onClick={() => downloadCsv(`${slug(p?.interview_type || "interview")}-report.csv`,
            ["Question", "Answer summary", "Relevance", "Correctness", "Clarity", "Completeness", "Skipped", "Stronger answer (AI example)"],
            report.questions.map((q) => [q.question, q.answer_summary, q.relevance, q.correctness, q.clarity_structure, q.completeness, q.skipped ? "yes" : "no", q.improved_answer]))}>
            Download questions (CSV)
          </button>
        </div>
      </section>

      {report.evidence_note && <p className="note">{report.evidence_note}</p>}

      <section>
        <h2>How you did on each criterion</h2>
        <ul className="criteria">
          {report.criteria.map((c) => (
            <li key={c.name}>
              <div className="crit-top"><span>{c.name}</span><Score value={c.score} /></div>
              <p>{c.comment}</p>
            </li>
          ))}
        </ul>
      </section>

      <div className="two-col">
        <section>
          <h2>Strong points</h2>
          <ul className="plain dots">{report.strengths.map((s) => <li key={s}>{s}</li>)}</ul>
        </section>
        <section>
          <h2>What to improve</h2>
          <ul className="plain dots">{report.areas_to_improve.map((s) => <li key={s}>{s}</li>)}</ul>
        </section>
      </div>

      <section>
        <h2>Question by question</h2>
        {report.questions.length === 0 && <p className="muted">No interview questions were recorded.</p>}
        {report.questions.map((q, i) => (
          <details key={i} className="question">
            <summary>
              <span className="qnum">Question {i + 1}</span>
              <span className="qtext">{q.question}</span>
              {q.skipped && <span className="tag subtle">Not answered</span>}
              {q.difficulty && <span className="tag subtle">{q.difficulty}</span>}
            </summary>
            <p><b>What you said:</b> {q.answer_summary}</p>
            <div className="qscores">
              <span>Relevance <Score value={q.relevance} /></span>
              <span>Correctness <Score value={q.correctness} /></span>
              <span>Clarity and structure <Score value={q.clarity_structure} /></span>
              <span>Completeness <Score value={q.completeness} /></span>
            </div>
            {q.objective_errors.length > 0 && (
              <div className="facts">
                <h3>Factual errors</h3>
                <ul className="plain dots">{q.objective_errors.map((e) => <li key={e}>{e}</li>)}</ul>
              </div>
            )}
            {q.subjective_feedback.length > 0 && (
              <div>
                <h3>Communication feedback (opinion)</h3>
                <ul className="plain dots">{q.subjective_feedback.map((e) => <li key={e}>{e}</li>)}</ul>
              </div>
            )}
            {q.strengths.length > 0 && <p><b>Worked well:</b> {q.strengths.join("; ")}</p>}
            {q.improvements.length > 0 && <p><b>To improve:</b> {q.improvements.join("; ")}</p>}
            <div className="better">
              <h3>A stronger answer could sound like <span className="tag subtle">AI example</span></h3>
              <p>{q.improved_answer}</p>
            </div>
          </details>
        ))}
      </section>

      <section>
        <h2>Your preparation plan</h2>
        <ol className="prep">
          {report.preparation_plan.map((item) => (
            <li key={item.topic}>
              <b>{item.topic}</b>
              <p>{item.why}</p>
              <p className="muted">{item.how_to_practise}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

export default function ResultsScreen({ report, onDone, onOpenWorksheet, actions }: {
  report: Report; onDone: () => void; onOpenWorksheet: (id: string) => void; actions?: ReportActions;
}) {
  return (
    <section className="results">
      <ReportView report={report} actions={actions} />
      {report.question_log && report.question_log.length > 0 && (
        <section className="card all-questions">
          <h2>All questions from this session</h2>
          <p className="muted">Click a question to see your answer. Saved sessions also get a full worksheet with model answers.</p>
          <QuestionList items={report.question_log} />
        </section>
      )}
      <div className="controls">
        <button className="primary" onClick={onDone}>Practise again</button>
        {report.saved && report.session_id && (
          <button onClick={() => onOpenWorksheet(report.session_id!)}>Open worksheet</button>
        )}
        <span className="muted">
          {report.saved ? "Saved to History on this laptop." : "Not saved. You chose not to save reports for this session."}
        </span>
      </div>
    </section>
  );
}
