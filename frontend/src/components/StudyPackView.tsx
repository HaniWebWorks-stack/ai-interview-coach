import { useState } from "react";
import type { StudyPackData } from "../types";
import { downloadCsv, slug } from "../download";

type Tab = "notes" | "flashcards" | "quiz" | "bank" | "frameworks" | "checklist";

function Flashcards({ cards }: { cards: StudyPackData["flashcards"] }) {
  const [i, setI] = useState(0);
  const [flipped, setFlipped] = useState(false);
  if (!cards.length) return <p className="muted">No flashcards in this pack.</p>;
  const c = cards[i];
  const go = (d: number) => { setI((i + d + cards.length) % cards.length); setFlipped(false); };
  return (
    <div className="fc">
      <button className={`fc-card ${flipped ? "is-flipped" : ""}`} onClick={() => setFlipped(!flipped)}
        aria-label={flipped ? `Answer: ${c.back}. Click to see the question.` : `Question: ${c.front}. Click to see the answer.`}>
        <span className="fc-side">{flipped ? "Answer" : "Question"}</span>
        <span className="fc-text">{flipped ? c.back : c.front}</span>
        <span className="fc-hint muted">{flipped ? "Click to see the question" : "Click to reveal the answer"}</span>
      </button>
      <div className="row-actions">
        <button onClick={() => go(-1)}>Previous</button>
        <span className="muted">Card {i + 1} of {cards.length}</span>
        <button onClick={() => go(1)}>Next</button>
      </div>
    </div>
  );
}

function Quiz({ items }: { items: StudyPackData["quiz"] }) {
  const [answers, setAnswers] = useState<Record<number, number>>({});
  if (!items.length) return <p className="muted">No quiz in this pack.</p>;
  const done = Object.keys(answers).length;
  const right = items.filter((q, i) => answers[i] === q.answer_index).length;
  return (
    <div className="quiz">
      <p className="muted" role="status">{done ? `${right} of ${done} correct so far` : "Choose an answer for each question."}</p>
      {items.map((q, i) => (
        <fieldset key={i} className="quiz-q">
          <legend>{i + 1}. {q.question}</legend>
          {q.options.map((o, j) => {
            const chosen = answers[i] === j;
            const state = answers[i] === undefined ? "" : j === q.answer_index ? "is-right" : chosen ? "is-wrong" : "";
            return (
              <label key={j} className={`quiz-opt ${state}`}>
                <input type="radio" name={`q${i}`} checked={chosen} disabled={answers[i] !== undefined}
                  onChange={() => setAnswers({ ...answers, [i]: j })} />
                <span>{o}</span>
                {state === "is-right" && <span className="quiz-mark">✓ Correct answer</span>}
                {state === "is-wrong" && <span className="quiz-mark">✗ Your answer</span>}
              </label>
            );
          })}
          {answers[i] !== undefined && <p className="quiz-exp">{q.explanation}</p>}
        </fieldset>
      ))}
      {done > 0 && <button onClick={() => setAnswers({})}>Start the quiz again</button>}
    </div>
  );
}

export default function StudyPackView({ pack }: { pack: StudyPackData }) {
  const [tab, setTab] = useState<Tab>("notes");
  const tabs: { id: Tab; label: string; n: number }[] = [
    { id: "notes", label: "Notes", n: pack.notes.length + pack.definitions.length },
    { id: "flashcards", label: "Flashcards", n: pack.flashcards.length },
    { id: "quiz", label: "Quiz", n: pack.quiz.length },
    { id: "bank", label: "Question bank", n: pack.question_bank.length },
    { id: "frameworks", label: "Answer frameworks", n: pack.frameworks.length },
    { id: "checklist", label: "Checklist", n: pack.checklist.length },
  ];
  const exportBank = () => downloadCsv(`${slug(pack.title)}-questions.csv`,
    ["Question", "Type", "Difficulty", "Model answer", "Key points"],
    pack.question_bank.map((q) => [q.question, q.type, q.difficulty, q.model_answer, q.key_points.join("; ")]));

  const notes = (
    <section className="sp-sec">
      {pack.notes.map((n) => <article key={n.heading} className="sp-note"><h3>{n.heading}</h3><p>{n.body}</p></article>)}
      {pack.definitions.length > 0 && (
        <>
          <h3>Key definitions</h3>
          <dl className="sp-defs">{pack.definitions.map((d) => <div key={d.term}><dt>{d.term}</dt><dd>{d.meaning}</dd></div>)}</dl>
        </>
      )}
    </section>
  );
  const bank = (
    <section className="sp-sec">
      {pack.question_bank.map((q, i) => (
        <details key={i} className="question">
          <summary><span className="qnum">{q.type}, {q.difficulty}</span><span className="qtext">{q.question}</span></summary>
          <div className="better"><h3>Model answer</h3><p>{q.model_answer}</p></div>
          {q.key_points.length > 0 && <ul className="plain dots">{q.key_points.map((k) => <li key={k}>{k}</li>)}</ul>}
        </details>
      ))}
    </section>
  );
  const frameworks = (
    <section className="sp-sec">
      {pack.frameworks.map((f) => (
        <article key={f.name} className="sp-note">
          <h3>{f.name}</h3>
          <ol className="sp-steps">{f.steps.map((s) => <li key={s.name}><b>{s.name}:</b> {s.guidance}</li>)}</ol>
          {f.example && <div className="better"><h3>Example</h3><p>{f.example}</p></div>}
        </article>
      ))}
    </section>
  );
  const checklist = <ul className="sp-check">{pack.checklist.map((c) => <li key={c}><label><input type="checkbox" /> {c}</label></li>)}</ul>;

  return (
    <div className="sp">
      <div className="sp-head no-print">
        <div className="sp-tabs" role="tablist" aria-label="Study pack sections">
          {tabs.filter((t) => t.n > 0).map((t) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>
              {t.label} <span className="muted">({t.n})</span>
            </button>
          ))}
        </div>
        <div className="row-actions">
          <button onClick={() => window.print()}>Print / Save as PDF</button>
          {pack.question_bank.length > 0 && <button onClick={exportBank}>Download question bank (CSV)</button>}
        </div>
      </div>
      <div className="no-print">
        {tab === "notes" && notes}
        {tab === "flashcards" && <Flashcards cards={pack.flashcards} />}
        {tab === "quiz" && <Quiz items={pack.quiz} />}
        {tab === "bank" && bank}
        {tab === "frameworks" && frameworks}
        {tab === "checklist" && checklist}
      </div>
      {/* Printed version: every section, in order. */}
      <div className="print-only sp-print">
        <h1>{pack.title}</h1>
        <h2>Revision notes</h2>{notes}
        {pack.frameworks.length > 0 && <><h2>Answer frameworks</h2>{frameworks}</>}
        {pack.question_bank.length > 0 && (
          <><h2>Question bank</h2>
            {pack.question_bank.map((q, i) => (
              <div key={i} className="sp-note"><h3>{i + 1}. {q.question}</h3><p>{q.model_answer}</p>
                <ul>{q.key_points.map((k) => <li key={k}>{k}</li>)}</ul></div>
            ))}</>
        )}
        {pack.flashcards.length > 0 && <><h2>Flashcards</h2><dl className="sp-defs">{pack.flashcards.map((c) => <div key={c.front}><dt>{c.front}</dt><dd>{c.back}</dd></div>)}</dl></>}
        {pack.quiz.length > 0 && <><h2>Quiz</h2><ol>{pack.quiz.map((q) => <li key={q.question}>{q.question}<ol type="A">{q.options.map((o) => <li key={o}>{o}</li>)}</ol></li>)}</ol>
          <p><b>Answers:</b> {pack.quiz.map((q, i) => `${i + 1}${"ABCD"[q.answer_index]}`).join(", ")}</p></>}
        {pack.checklist.length > 0 && <><h2>Checklist</h2>{checklist}</>}
        <p className="muted">AI-generated study material from AI Interview Coach. Check important facts.</p>
      </div>
    </div>
  );
}
