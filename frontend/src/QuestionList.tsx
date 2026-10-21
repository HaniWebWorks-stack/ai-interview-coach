import type { QuestionEntry } from "./types";

/** Questions the coach asked. Click a question to see your answer and the feedback. */
export default function QuestionList({ items, openFirst = false, emptyText }: {
  items: QuestionEntry[];
  openFirst?: boolean;
  emptyText?: string;
}) {
  if (!items.length) return <p className="muted">{emptyText || "No questions yet."}</p>;
  let practice = 0;
  let interview = 0;
  return (
    <ol className="qlist">
      {items.map((q, i) => {
        const n = q.phase === "practice" ? ++practice : ++interview;
        return (
          <li key={i}>
            <details open={openFirst && i === 0}>
              <summary>
                <span className={`qtag ${q.phase}`}>{q.phase === "practice" ? `Practice ${n}` : `Interview ${n}`}</span>
                <span className="qtext">{q.question}</span>
              </summary>
              <div className="qbody">
                <p><b>Your answer:</b> {q.answer || <span className="muted">No answer recorded.</span>}</p>
                {q.feedback && <p><b>Coach's feedback:</b> {q.feedback}</p>}
                {q.improvements && q.improvements.length > 0 && (
                  <p><b>To improve:</b> {q.improvements.join("; ")}</p>
                )}
                {q.improved_answer && (
                  <div className="better">
                    <h3>A stronger answer could sound like</h3>
                    <p>{q.improved_answer}</p>
                  </div>
                )}
              </div>
            </details>
          </li>
        );
      })}
    </ol>
  );
}
