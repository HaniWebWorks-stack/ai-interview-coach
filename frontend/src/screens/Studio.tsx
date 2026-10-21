import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { DiagramData, DiagramKind, DNode, Focus, InsightsData, Material, StudyPackData, Weakness } from "../types";
import { downloadCsv, slug } from "../download";
import StudyPackView from "../components/StudyPackView";

const DiagramViewer = lazy(() => import("../components/DiagramViewer"));

export interface StudioRequest { type: "diagram" | "studypack"; topic: string; kind?: DiagramKind }

const KINDS: { id: DiagramKind | "studypack"; label: string; hint: string }[] = [
  { id: "mindmap", label: "Mind map", hint: "A central topic with branches to explore" },
  { id: "concept", label: "Concept diagram", hint: "How ideas connect, with examples" },
  { id: "flowchart", label: "Process flowchart", hint: "Step by step, with decisions" },
  { id: "star", label: "Answer structure (STAR)", hint: "How to build a strong answer" },
  { id: "skillgap", label: "Skill-gap diagram", hint: "Built from your saved sessions only" },
  { id: "roadmap", label: "Learning roadmap", hint: "Your study plan with trackable tasks" },
  { id: "studypack", label: "Study pack", hint: "Notes, flashcards, quiz, question bank, checklist" },
];
const KIND_LABEL: Record<Weakness["kind"], string> = {
  knowledge_gap: "Knowledge gap",
  incomplete_answer: "Incomplete answers",
  weak_examples: "Weak or missing examples",
  unclear_communication: "Unclear explanation",
  lacks_structure: "Answers lack structure",
};
const REASSESS_LABEL = { improved: "✓ Improved", still_weak: "! Still needs work", not_reassessed: "○ Not reassessed yet" };

function Skeleton({ label }: { label: string }) {
  return (
    <div className="skeleton" role="status" aria-live="polite">
      <span className="sk-bar" /><span className="sk-bar short" /><span className="sk-bar" />
      <p className="muted">{label}</p>
    </div>
  );
}

export default function StudioScreen({ onPractice, onAsk, request, clearRequest }: {
  onPractice: (f: Focus) => void;
  onAsk: (ctx: { type: "material" | "insights" | "general"; id?: string; node_id?: string; label?: string }) => void;
  request: StudioRequest | null;
  clearRequest: () => void;
}) {
  const [insights, setInsights] = useState<Material<InsightsData> | null>(null);
  const [stale, setStale] = useState(false);
  const [sessionCount, setSessionCount] = useState<number | null>(null);
  const [analysing, setAnalysing] = useState(false);
  const [library, setLibrary] = useState<Material[] | null>(null);
  const [open, setOpen] = useState<Material | null>(null);
  const [topic, setTopic] = useState("");
  const [kind, setKind] = useState<DiagramKind | "studypack">("mindmap");
  const [personal, setPersonal] = useState(true);
  const [creating, setCreating] = useState("");
  const [error, setError] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const loadLibrary = useCallback(() => {
    api.materials().then((d) => setLibrary(d.materials.filter((m) => m.kind !== "insights"))).catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    api.insights().then((d) => { setInsights(d.insights); setStale(d.stale); setSessionCount(d.session_count); })
      .catch((e) => setError((e as Error).message));
    loadLibrary();
  }, [loadLibrary]);

  const analyse = async (force = false) => {
    setAnalysing(true);
    setError("");
    try {
      const d = await api.makeInsights(force);
      setInsights(d.insights);
      setStale(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAnalysing(false);
    }
  };

  const create = useCallback(async (k: DiagramKind | "studypack", t: string, usePersonal = personal) => {
    const tp = t.trim();
    if (!tp) { setError("Enter a topic first."); return; }
    setError("");
    setCreating(k === "studypack" ? `Writing a study pack on "${tp}"…` : `Drawing a ${KINDS.find((x) => x.id === k)?.label.toLowerCase()} of "${tp}"…`);
    setOpen(null);
    const source = k === "skillgap" ? { type: "all" } : k === "roadmap" ? { type: "insights" } : usePersonal ? { type: "insights" } : undefined;
    try {
      const d = k === "studypack" ? await api.makeStudyPack(tp, source) : await api.makeDiagram(k, tp, source);
      const full = await api.material(d.material.id);
      setOpen(full.material);
      loadLibrary();
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreating("");
    }
  }, [personal, loadLibrary]);

  // Requests from elsewhere (assistant, report, progress page).
  useEffect(() => {
    if (!request) return;
    clearRequest();
    setTopic(request.topic);
    const k = request.type === "studypack" ? "studypack" : request.kind || "mindmap";
    setKind(k);
    void create(k, request.topic);
  }, [request, clearRequest, create]);

  const openMaterial = async (id: string) => {
    setError("");
    try {
      setOpen((await api.material(id)).material);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const remove = async (id: string) => {
    await api.deleteMaterial(id).catch((e) => setError((e as Error).message));
    setConfirmDelete(null);
    if (open?.id === id) setOpen(null);
    loadLibrary();
  };

  const practiseWeakness = (w: Weakness, reassess = false) => onPractice({
    topic: w.topic, kind: reassess ? "reassess" : "weakness", questions: w.practice_questions,
    notes: `${KIND_LABEL[w.kind]}: ${w.evidence}`.slice(0, 600),
  });

  const ins = insights?.data;
  const weaknessByTopic = (t: string) => ins?.weaknesses.find((w) => w.topic.toLowerCase() === t.toLowerCase());

  // ---------------- open material ----------------
  if (open) {
    const isDiagram = open.kind === "diagram" || open.kind === "resume_match";
    const diagram = (open.kind === "resume_match" ? (open.data as { diagram: DiagramData }).diagram : open.data) as DiagramData;
    const regenerate = open.kind === "diagram" ? () => {
      const src = open.source as { kind?: DiagramKind; topic?: string };
      if (src.kind && src.topic) void create(src.kind, src.topic);
    } : undefined;
    const exportRoadmap = () => downloadCsv(`${slug(diagram.title)}-tracker.csv`, ["Milestone/task", "Type", "Status", "Details", "Practice questions"],
      diagram.nodes.map((n) => [n.label, n.role, n.role === "task" ? (n.status || "pending").replace("_", " ") : "", n.detail, (n.questions || []).join(" | ")]));
    return (
      <section className="studio">
        <div className="studio-open-head no-print">
          <button className="quiet" onClick={() => setOpen(null)}>Back to the Studio</button>
          <div className="row-actions wrap">
            <button onClick={() => onAsk({ type: "material", id: open.id, label: open.title })}>Ask the assistant about this</button>
            {isDiagram && diagram.kind === "roadmap" && <button onClick={exportRoadmap}>Download progress tracker (CSV)</button>}
            {isDiagram && <button onClick={() => window.print()}>Print / Save as PDF</button>}
          </div>
        </div>
        <h1>{open.title}</h1>
        <p className="muted">Created {new Date(open.created_at * 1000).toLocaleString()} · AI-generated study material, check important facts.</p>
        {creating && <Skeleton label={creating} />}
        {error && <p className="error-text" role="alert">{error}</p>}
        {isDiagram ? (
          <Suspense fallback={<Skeleton label="Opening the diagram…" />}>
            <DiagramViewer
              materialId={open.kind === "diagram" ? open.id : undefined}
              data={diagram}
              regenerating={!!creating}
              onRegenerate={regenerate}
              onPractice={(t, qs) => onPractice({ topic: t, kind: "studio", questions: qs })}
              onAsk={(n: DNode) => onAsk({ type: "material", id: open.id, node_id: n.id, label: n.label })}
            />
            <div className="print-only">
              <ul>{diagram.nodes.map((n) => <li key={n.id}><b>{n.label}</b>{n.detail ? `: ${n.detail}` : ""}{n.status ? ` [${n.status.replace("_", " ")}]` : ""}</li>)}</ul>
            </div>
          </Suspense>
        ) : (
          <StudyPackView pack={open.data as StudyPackData} />
        )}
      </section>
    );
  }

  // ---------------- studio home ----------------
  return (
    <section className="studio">
      <div className="page-head">
        <div>
          <h1>Preparation Studio</h1>
          <p className="muted">Turns your saved practice sessions and mock interviews into targeted study material: diagrams, notes, quizzes and a learning roadmap.</p>
        </div>
        <button onClick={() => onAsk({ type: ins ? "insights" : "general", label: ins ? "your preparation insights" : undefined })}>Ask the assistant</button>
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      {creating && <Skeleton label={creating} />}

      <section className="card studio-sec" aria-labelledby="ins-h">
        <div className="sec-head">
          <h2 id="ins-h">What to work on next</h2>
          {ins && <button onClick={() => void analyse(true)} disabled={analysing}>{analysing ? "Analysing…" : stale ? "Update with new sessions" : "Analyse again"}</button>}
        </div>
        {analysing && <Skeleton label="Reading your saved sessions and finding patterns… (about 10 to 30 seconds)" />}
        {!ins && !analysing && (
          sessionCount === 0 ? (
            <p className="empty">No saved sessions yet. Tick "Save my interview report" on the Practice page; after a session, come back here and the Studio will find your strengths and weak spots.</p>
          ) : (
            <div className="empty">
              <p>{sessionCount ?? "…"} saved session{sessionCount === 1 ? "" : "s"} found. Analyse them to see recurring weak spots, strengths and what to practise next.</p>
              <button className="primary" onClick={() => void analyse()} disabled={sessionCount === null}>Analyse my sessions</button>
            </div>
          )
        )}
        {ins && !analysing && (
          <>
            {stale && <p className="note strong">You have new saved sessions since this analysis. Update it to include them.</p>}
            <p className="lead-sm">{ins.summary}</p>
            <p className="muted small">Based on {(insights?.source.session_ids as string[] | undefined)?.length ?? "your"} saved sessions, analysed {new Date((insights?.created_at || 0) * 1000).toLocaleDateString()}. AI analysis of real results; scores are estimates.</p>

            {ins.weaknesses.length > 0 && <h3>Weak spots, most important first</h3>}
            <div className="weak-grid">
              {ins.weaknesses.map((w) => (
                <article key={w.id} className={`weak sev-${w.severity}`}>
                  <header>
                    <h4>{w.topic}</h4>
                    <span className="tag">{KIND_LABEL[w.kind]}</span>
                    <span className="tag subtle">{w.severity === "high" ? "▲ High" : w.severity === "medium" ? "■ Medium" : "▼ Low"} priority · seen {w.occurrences}×</span>
                  </header>
                  <p className="small"><b>Evidence:</b> {w.evidence}</p>
                  <details>
                    <summary>Revision note, answer framework and new practice questions</summary>
                    <p>{w.revision_note}</p>
                    {w.framework && <p><b>How to structure your answer:</b> {w.framework}</p>}
                    {w.why_it_matters && <p className="muted">{w.why_it_matters}</p>}
                    <ol>{w.practice_questions.map((q) => <li key={q}>{q}</li>)}</ol>
                  </details>
                  <div className="row-actions wrap">
                    <button className="primary" onClick={() => practiseWeakness(w)}>Practise with the coach</button>
                    <button onClick={() => void create("concept", w.topic, true)}>Concept diagram</button>
                    <button onClick={() => void create("studypack", w.topic, true)}>Study pack</button>
                  </div>
                </article>
              ))}
            </div>

            {ins.recommendations.length > 0 && (
              <>
                <h3>Recommended next steps</h3>
                <ol className="recs">
                  {ins.recommendations.map((r) => (
                    <li key={r.title}>
                      <div><b>{r.title}</b><p className="small muted">{r.why}</p></div>
                      <button onClick={() => {
                        const w = weaknessByTopic(r.topic);
                        if (r.action === "practice") onPractice({ topic: r.topic, kind: "recommendation", questions: w?.practice_questions, notes: r.why });
                        else if (r.action === "diagram") void create("mindmap", r.topic, true);
                        else void create("studypack", r.topic, true);
                      }}>{r.action === "practice" ? "Practise" : r.action === "diagram" ? "Make a mind map" : "Make a study pack"}</button>
                    </li>
                  ))}
                </ol>
              </>
            )}

            <div className="two-col">
              {ins.strengths.length > 0 && (
                <section>
                  <h3>Consistent strengths</h3>
                  <ul className="plain dots">{ins.strengths.map((s) => <li key={s.topic}><b>{s.topic}:</b> <span className="small">{s.evidence}</span></li>)}</ul>
                </section>
              )}
              {ins.reassessment.length > 0 && (
                <section>
                  <h3>Earlier weak spots: reassessed?</h3>
                  <ul className="plain">
                    {ins.reassessment.map((r) => (
                      <li key={r.topic} className="reassess">
                        <span><b>{r.topic}</b> <span className={`tag st-${r.status}`}>{REASSESS_LABEL[r.status]}</span></span>
                        <span className="small muted">{r.evidence}</span>
                        {r.status !== "improved" && (
                          <button className="small" onClick={() => {
                            const w = weaknessByTopic(r.topic);
                            onPractice({ topic: r.topic, kind: "reassess", questions: w?.practice_questions, notes: r.evidence });
                          }}>Reassess with new questions</button>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
            <div className="row-actions wrap">
              <button onClick={() => void create("roadmap", "My interview preparation", true)}>Build my learning roadmap</button>
              <button onClick={() => void create("skillgap", "Skills for my target role", true)}>Show my skill-gap diagram</button>
            </div>
          </>
        )}
      </section>

      <section className="card studio-sec" aria-labelledby="mk-h">
        <h2 id="mk-h">Create study material</h2>
        <form className="mk-form" onSubmit={(e) => { e.preventDefault(); void create(kind, topic); }}>
          <label className="mk-topic">Topic
            <input value={topic} maxLength={200} onChange={(e) => setTopic(e.target.value)}
              placeholder="e.g. Python decorators, handling objections, the STAR method" />
          </label>
          {ins && ins.weaknesses.length > 0 && (
            <div className="chips" aria-label="Suggested topics from your weak spots">
              {ins.weaknesses.map((w) => <button type="button" key={w.id} className="chip" onClick={() => setTopic(w.topic)}>{w.topic}</button>)}
            </div>
          )}
          <fieldset className="mk-kinds">
            <legend>What to create</legend>
            {KINDS.map((k) => (
              <label key={k.id} className={`mk-kind ${kind === k.id ? "chosen" : ""}`}>
                <input type="radio" name="kind" checked={kind === k.id} onChange={() => setKind(k.id)} />
                <span><b>{k.label}</b><small>{k.hint}</small></span>
              </label>
            ))}
          </fieldset>
          {kind !== "skillgap" && kind !== "roadmap" && (
            <label className="check inline">
              <input type="checkbox" checked={personal} onChange={(e) => setPersonal(e.target.checked)} />
              <span>Tailor it to my saved sessions (uses your latest analysis)</span>
            </label>
          )}
          <button className="primary" type="submit" disabled={!!creating || !topic.trim()}>{creating ? "Creating…" : "Create"}</button>
        </form>
      </section>

      <section className="card studio-sec" aria-labelledby="lib-h">
        <h2 id="lib-h">Your library</h2>
        {!library && <Skeleton label="Loading your saved material…" />}
        {library && library.length === 0 && <p className="empty">Nothing saved yet. Everything you create here is saved on this laptop.</p>}
        {library && library.length > 0 && (
          <ul className="lib">
            {library.map((m) => (
              <li key={m.id}>
                <span className="tag">{m.kind === "studypack" ? "Study pack" : m.kind === "resume_match" ? "Resume match" : KINDS.find((k) => k.id === (m.source as { kind?: string }).kind)?.label || "Diagram"}</span>
                <button className="link lib-title" onClick={() => void openMaterial(m.id)}>{m.title}</button>
                <span className="muted small">{new Date(m.created_at * 1000).toLocaleDateString()}</span>
                {confirmDelete === m.id ? (
                  <span className="confirm small">Delete for good?
                    <button className="danger" onClick={() => void remove(m.id)}>Delete</button>
                    <button onClick={() => setConfirmDelete(null)}>Keep</button>
                  </span>
                ) : (
                  <button className="danger-text" onClick={() => setConfirmDelete(m.id)} aria-label={`Delete ${m.title}`}>Delete</button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}
