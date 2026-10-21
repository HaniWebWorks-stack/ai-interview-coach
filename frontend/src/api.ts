import type {
  AssistantAction, AssistantContext, AssistantMessage, AvatarInfo, DiagramData, DiagramKind, Focus, HistoryItem,
  InsightsData, Material, ProgressData, QuestionSession, Report, ResumeMatchData, Settings, StudyPackData, WorksheetData,
} from "./types";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* no body */
  }
  if (!res.ok) {
    const msg = (data as { error?: string } | null)?.error || `The local server answered ${res.status}.`;
    throw new Error(msg);
  }
  return data as T;
}

export const api = {
  token: (saveHistory: boolean, focus?: Focus | null) =>
    call<{ url: string; token: string; room: string }>("/api/token", {
      method: "POST",
      body: JSON.stringify({ save_history: saveHistory, ...(focus ? { focus } : {}) }),
    }),
  settings: () => call<Settings>("/api/settings"),
  saveSettings: (patch: Partial<Settings>) =>
    call<Settings>("/api/settings", { method: "POST", body: JSON.stringify(patch) }),
  avatars: () => call<{ avatars: AvatarInfo[] }>("/api/avatars"),
  credits: () => call<{ credits_left: string | null }>("/api/status"),
  history: () => call<{ sessions: HistoryItem[]; stored_at: string }>("/api/history"),
  historyItem: (id: string) =>
    call<{ report: Report; transcript: { role: string; text: string }[] } & HistoryItem>(`/api/history/${id}`),
  deleteHistory: (id: string) => call<{ deleted: boolean }>(`/api/history/${id}`, { method: "DELETE" }),
  progress: (category = "", role = "") =>
    call<ProgressData>(`/api/progress?category=${encodeURIComponent(category)}&role=${encodeURIComponent(role)}`),
  insights: () => call<{ insights: Material<InsightsData> | null; stale: boolean; session_count: number }>("/api/insights"),
  makeInsights: (force = false) =>
    call<{ insights: Material<InsightsData>; cached: boolean }>("/api/insights", { method: "POST", body: JSON.stringify({ force }) }),
  makeDiagram: (kind: DiagramKind, topic: string, source?: { type: string; id?: string }) =>
    call<{ material: Material<DiagramData> }>("/api/diagrams", { method: "POST", body: JSON.stringify({ kind, topic, source }) }),
  makeStudyPack: (topic: string, source?: { type: string; id?: string }) =>
    call<{ material: Material<StudyPackData> }>("/api/studypacks", { method: "POST", body: JSON.stringify({ topic, source }) }),
  materials: (kind?: string) => call<{ materials: Material[] }>(`/api/materials${kind ? `?kind=${kind}` : ""}`),
  material: <T,>(id: string) => call<{ material: Material<T> }>(`/api/materials/${id}`),
  editNode: (id: string, node_id: string, patch: { label?: string; note?: string }) =>
    call<{ node: unknown }>(`/api/materials/${id}`, { method: "PATCH", body: JSON.stringify({ node_id, ...patch }) }),
  deleteMaterial: (id: string) => call<{ deleted: boolean }>(`/api/materials/${id}`, { method: "DELETE" }),
  setProgressItem: (key: string, status: string) =>
    call<{ key: string; status: string }>("/api/progress-items", { method: "POST", body: JSON.stringify({ key, status }) }),
  resumeExtract: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/resume/extract", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error((data as { error?: string }).error || `The local server answered ${res.status}.`);
    return data as { text: string; chars: number };
  },
  resumeMatch: (resume_text: string, job_description: string, save: boolean) =>
    call<{ material: Material<ResumeMatchData>; saved: boolean }>("/api/resume/match", {
      method: "POST", body: JSON.stringify({ resume_text, job_description, save }),
    }),
  assistant: (context: AssistantContext, messages: AssistantMessage[]) =>
    call<{ reply: string } & AssistantAction>("/api/assistant", {
      method: "POST", body: JSON.stringify({ context, messages: messages.map(({ role, text }) => ({ role, text })) }),
    }),
  worksheet: (id: string) => call<WorksheetData>(`/api/worksheet/${id}`),
  questions: () => call<{ sessions: QuestionSession[] }>("/api/questions"),
  deleteAllHistory: () => call<{ deleted: number }>("/api/history", { method: "DELETE" }),
};
