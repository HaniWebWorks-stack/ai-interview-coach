import { lazy, Suspense, useEffect, useState } from "react";
import { api } from "../api";
import type { Focus, Material, ResumeMatchData, SkillRow } from "../types";
import { downloadCsv, slug } from "../download";

const DiagramViewer = lazy(() => import("../components/DiagramViewer"));
const MAX_BYTES = 5 * 1024 * 1024;

/** Read a PDF's text in the browser (pdf.js), so no extra software is needed on the laptop. */
async function pdfText(file: File): Promise<string> {
  const pdfjs = await import("pdfjs-dist");
  const worker = (await import("pdfjs-dist/build/pdf.worker.min.mjs?url")).default;
  pdfjs.GlobalWorkerOptions.workerSrc = worker;
  const doc = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise;
  const pages: string[] = [];
  for (let i = 1; i <= Math.min(doc.numPages, 15); i++) {
    const content = await (await doc.getPage(i)).getTextContent();
    pages.push(content.items.map((it) => ("str" in it ? it.str + (it.hasEOL ? "\n" : " ") : "")).join(""));
  }
  return pages.join("\n\n").replace(/[ \t]+/g, " ").trim();
}

const STATUS: Record<SkillRow["status"], { label: string; icon: string }> = {
  demonstrated: { label: "Shown in resume", icon: "✓" },
  partial: { label: "Partly shown", icon: "◐" },
  not_mentioned: { label: "Not mentioned", icon: "○" },
};

export default function ResumeMatchScreen({ onPractice }: { onPractice: (f: Focus) => void }) {
  const [resumeText, setResumeText] = useState("");
  const [job, setJob] = useState("");
  const [save, setSave] = useState(true);
  const [reading, setReading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Material<ResumeMatchData> | null>(null);
  const [saved, setSaved] = useState<Material[] | null>(null);
  const [fileNote, setFileNote] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const loadSaved = () => api.materials("resume_match").then((d) => setSaved(d.materials)).catch(() => setSaved([]));
  useEffect(() => { void loadSaved(); }, []);

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setError("");
    setFileNote("");
    if (file.size > MAX_BYTES) { setError("The file is larger than 5 MB. Please choose a smaller file."); return; }
    const name = file.name.toLowerCase();
    if (!/\.(pdf|docx|txt)$/.test(name)) { setError("Please choose a .pdf, .docx or .txt file."); return; }
    setReading(true);
    try {
      const text = name.endsWith(".pdf") ? await pdfText(file) : (await api.resumeExtract(file)).text;
      if (text.length < 80) throw new Error("Very little text was found. If this is a scanned image, paste the text instead.");
      setResumeText(text.slice(0, 30000));
      setFileNote(`Read ${text.length.toLocaleString()} characters from ${file.name}. Check the text below and correct anything that was misread.`);
    } catch (e) {
      setError((e as Error).message || "The file could not be read.");
    } finally {
      setReading(false);
    }
  };

  const analyse = async () => {
    setBusy(true);
    setError("");
    try {
      const d = await api.resumeMatch(resumeText, job, save);
      setResult(d.material);
      if (d.saved) void loadSaved();
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    const r = result.data;
    const practise = () => onPractice({
      topic: `${r.role_title} interview`, kind: "resume", role: r.role_title, interview_type: `${r.role_title} interview`,
      questions: [...r.questions.resume_followups.slice(0, 2), ...r.questions.technical.slice(0, 2), ...r.questions.behavioral.slice(0, 1)],
      notes: `Skills not shown in the resume: ${r.skills.filter((s) => s.status !== "demonstrated").map((s) => s.skill).slice(0, 6).join(", ")}`,
    });
    const exportCsv = () => downloadCsv(`${slug(r.role_title)}-skill-match.csv`, ["Skill", "Importance", "Status", "Evidence from resume", "Note"],
      r.skills.map((s) => [s.skill, s.importance, STATUS[s.status].label, s.evidence_quote, s.note]));
    return (
      <section className="resume">
        <div className="studio-open-head no-print">
          <button className="quiet" onClick={() => setResult(null)}>Back</button>
          <div className="row-actions wrap">
            <button className="primary" onClick={practise}>Practise for this job with the coach</button>
            <button onClick={exportCsv}>Download skill table (CSV)</button>
            <button onClick={() => window.print()}>Print / Save as PDF</button>
          </div>
        </div>
        <h1>Resume match: {r.role_title}</h1>
        <p className="lead-sm">{r.summary}</p>
        <p className="note">{r.caveat}</p>
        <div className="tiles">
          <div className="tile"><span className="tile-num">✓ {r.counts.demonstrated}</span><span>shown in your resume</span></div>
          <div className="tile"><span className="tile-num">◐ {r.counts.partial}</span><span>partly shown</span></div>
          <div className="tile"><span className="tile-num">○ {r.counts.not_mentioned}</span><span>not mentioned (prepare to talk about these)</span></div>
        </div>

        <section className="card">
          <h2>Skill-match diagram</h2>
          <Suspense fallback={<p className="muted">Opening the diagram…</p>}>
            <DiagramViewer data={r.diagram} onPractice={(t, qs) => onPractice({ topic: t, kind: "resume", role: r.role_title, questions: qs })} />
          </Suspense>
        </section>

        <section className="card">
          <h2>Skill by skill</h2>
          <div className="table-scroll">
            <table className="skill-table">
              <thead><tr><th scope="col">Skill</th><th scope="col">Job needs it</th><th scope="col">Your resume</th><th scope="col">Evidence (copied from your resume)</th></tr></thead>
              <tbody>
                {r.skills.map((s) => (
                  <tr key={s.skill}>
                    <td><b>{s.skill}</b>{s.note && <div className="small muted">{s.note}</div>}</td>
                    <td>{s.importance === "required" ? "Required" : "Preferred"}</td>
                    <td><span className={`status st-${s.status}`}>{STATUS[s.status].icon} {STATUS[s.status].label}</span></td>
                    <td className="small">{s.evidence_quote ? `"${s.evidence_quote}"` : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <div className="two-col">
          <section className="card">
            <h2>Questions to prepare</h2>
            {([["Technical", r.questions.technical], ["Behavioural", r.questions.behavioral], ["About your resume", r.questions.resume_followups]] as const).map(([h, qs]) =>
              qs.length > 0 && <div key={h}><h3>{h}</h3><ol>{qs.map((q) => <li key={q}>{q}</li>)}</ol></div>)}
          </section>
          <section className="card">
            <h2>How to talk about your experience</h2>
            {r.talking_points.length ? r.talking_points.map((t) => <div key={t.project}><h3>{t.project}</h3><p>{t.how_to_explain}</p></div>)
              : <p className="muted">No specific projects could be matched to your resume text.</p>}
            <h2>Preparation roadmap</h2>
            <ol>{r.roadmap.map((s) => <li key={s.step}><b>{s.step}</b> <span className="small muted">({s.related_skill})</span><p className="small">{s.why}</p></li>)}</ol>
          </section>
        </div>
      </section>
    );
  }

  return (
    <section className="resume">
      <h1>Resume match</h1>
      <p className="muted">Compare your resume with a job description to see which required skills your resume shows, which it
        does not mention, and which questions to prepare. Nothing is invented: every "shown" skill is checked against your actual resume text.</p>
      <p className="note"><b>Privacy:</b> the resume and job text are sent to Google Gemini (the same service the coach uses) for this
        analysis. The resume text is never stored; if you tick "save", only the analysis is saved on this laptop.</p>
      {error && <p className="error-text" role="alert">{error}</p>}

      <div className="two-col">
        <section className="card">
          <h2>1. Your resume</h2>
          <label className="file-pick">Upload (.pdf, .docx or .txt, up to 5 MB)
            <input type="file" accept=".pdf,.docx,.txt" onChange={(e) => void onFile(e.target.files?.[0])} disabled={reading || busy} />
          </label>
          {reading && <p className="muted" role="status">Reading the file…</p>}
          {fileNote && <p className="muted small" role="status">{fileNote}</p>}
          <label>Or paste the text
            <textarea rows={12} value={resumeText} maxLength={30000} onChange={(e) => setResumeText(e.target.value)}
              placeholder="Paste your resume here" />
          </label>
          <p className="small muted">{resumeText.length.toLocaleString()} characters</p>
        </section>
        <section className="card">
          <h2>2. The job description</h2>
          <label>Paste the full job advert
            <textarea rows={15} value={job} maxLength={15000} onChange={(e) => setJob(e.target.value)}
              placeholder="Paste the job description here, including requirements" />
          </label>
          <p className="small muted">{job.length.toLocaleString()} characters</p>
        </section>
      </div>
      <div className="controls">
        <label className="check inline"><input type="checkbox" checked={save} onChange={(e) => setSave(e.target.checked)} />
          <span>Save the analysis on this laptop (not the resume)</span></label>
        <button className="primary big" onClick={() => void analyse()}
          disabled={busy || reading || resumeText.trim().length < 80 || job.trim().length < 80}>
          {busy ? "Comparing… (about 20 seconds)" : "Compare resume and job"}
        </button>
      </div>
      {(resumeText.trim().length < 80 || job.trim().length < 80) && !busy && (
        <p className="small muted">Add your resume and the job description (at least a few sentences each) to start.</p>
      )}

      {saved && saved.length > 0 && (
        <section className="card">
          <h2>Saved analyses</h2>
          <ul className="lib">
            {saved.map((m) => (
              <li key={m.id}>
                <button className="link lib-title" onClick={() => api.material<ResumeMatchData>(m.id).then((d) => setResult(d.material)).catch((e) => setError((e as Error).message))}>{m.title}</button>
                <span className="muted small">{new Date(m.created_at * 1000).toLocaleDateString()}</span>
                {confirmDelete === m.id ? (
                  <span className="confirm small">Delete this analysis?
                    <button className="danger" onClick={() => api.deleteMaterial(m.id).then(() => { setConfirmDelete(null); void loadSaved(); })}>Delete</button>
                    <button onClick={() => setConfirmDelete(null)}>Keep</button>
                  </span>
                ) : (
                  <button className="danger-text" onClick={() => setConfirmDelete(m.id)} aria-label={`Delete ${m.title}`}>Delete</button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </section>
  );
}
