import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { AssistantAction, AssistantContext, AssistantMessage } from "../types";

/*
 * Learning assistant drawer. It only sees the one item it was opened from
 * (a report, a diagram or the latest insights), never other sessions.
 * Suggested actions are real buttons that call the real generators.
 */

const STARTERS: Record<AssistantContext["type"], string[]> = {
  report: ["Why did my answers get this feedback?", "Help me improve my weakest answer", "Give me 3 new practice questions"],
  material: ["Explain this in simple words", "Give me an example", "Quiz me with a hint first"],
  insights: ["What should I practise first?", "Explain my biggest weakness simply", "Make a mind map of my weak areas"],
  general: ["Explain the STAR method", "How do I answer 'Tell me about yourself'?", "Make a flowchart for solving coding questions"],
};

export default function Assistant({ context, onClose, onAction }: {
  context: AssistantContext;
  onClose: () => void;
  onAction: (a: AssistantAction) => void;
}) {
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { setMessages([]); setError(""); inputRef.current?.focus(); }, [context.type, context.id, context.node_id]);
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight }); }, [messages, busy]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const send = async (text: string, base: AssistantMessage[] = messages) => {
    const t = text.trim();
    if (!t || busy) return;
    const next: AssistantMessage[] = [...base, { role: "user", text: t }];
    setMessages(next);
    setDraft("");
    setBusy(true);
    setError("");
    try {
      const r = await api.assistant(context, next);
      setMessages([...next, { role: "assistant", text: r.reply, action: r.action !== "none" ? r : undefined }]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const actionLabel = (a: AssistantAction) =>
    a.action === "diagram" ? `Draw a ${a.diagram_kind === "flowchart" ? "flowchart" : a.diagram_kind === "concept" ? "concept diagram" : a.diagram_kind === "star" ? "STAR diagram" : "mind map"} of "${a.action_topic}"`
      : a.action === "practice" ? `Practise "${a.action_topic}" with the coach`
        : `Create a study pack on "${a.action_topic}"`;

  return (
    <aside className="assistant" role="dialog" aria-modal="false" aria-label="Learning assistant">
      <header>
        <div>
          <h2>Learning assistant</h2>
          <p className="muted">{context.label ? `About: ${context.label}` : "Ask anything about interview preparation."}</p>
        </div>
        <button className="quiet" onClick={onClose} aria-label="Close the assistant">Close</button>
      </header>
      <div className="as-list" ref={listRef} aria-live="polite">
        {messages.length === 0 && (
          <div className="as-starters">
            <p className="muted">Try one of these:</p>
            {STARTERS[context.type].map((s) => <button key={s} onClick={() => void send(s)}>{s}</button>)}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`as-msg ${m.role === "user" ? "as-user" : "as-bot"}`}>
            <p>{m.text}</p>
            {m.action && m.action.action_topic && (
              <button className="primary small" onClick={() => onAction(m.action!)}>{actionLabel(m.action)}</button>
            )}
          </div>
        ))}
        {busy && <div className="as-msg as-bot as-typing" aria-label="The assistant is writing">Thinking…</div>}
        {error && <p className="error-text" role="alert">{error} <button className="link" onClick={() => {
          const last = messages[messages.length - 1];
          if (last?.role === "user") void send(last.text, messages.slice(0, -1));
        }}>Try again</button></p>}
      </div>
      <form className="as-form" onSubmit={(e) => { e.preventDefault(); void send(draft); }}>
        <label className="sr" htmlFor="as-input">Your question</label>
        <textarea id="as-input" ref={inputRef} rows={2} value={draft} maxLength={1500}
          placeholder="Ask a question…" onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(draft); } }} />
        <button className="primary" type="submit" disabled={busy || !draft.trim()}>Send</button>
      </form>
      <p className="as-foot muted">Answers are AI-generated study help and can be wrong. Check important facts.</p>
    </aside>
  );
}
