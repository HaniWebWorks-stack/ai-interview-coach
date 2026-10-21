export type Phase =
  | "discovery"
  | "preparation"
  | "ready_check"
  | "interview"
  | "closing"
  | "evaluating"
  | "finished";

export interface TimerSnapshot {
  duration_ms: number;
  elapsed_ms: number;
  running: boolean;
  as_of_ms: number;
}

export interface CoachState {
  phase: Phase;
  phase_label: string;
  paused: boolean;
  profile: {
    interview_type: string;
    role: string;
    experience_level: string;
    language: string;
    goals: string;
    category: string;
  };
  plan: string[];
  topics_covered: string[];
  questions_asked: number;
  timer: TimerSnapshot;
  avatar: {
    status: "off" | "starting" | "on" | "unavailable" | "ended" | "closed" | "3d";
    name: string;
    sandbox: boolean;
    reason?: "" | "no_credits" | "timeout" | "error";
  };
  session_id: string;
  save_history: boolean;
}

export interface TranscriptLine {
  id: string;
  role: "user" | "assistant";
  text: string;
  phase: Phase;
  interrupted: boolean;
  t: number;
}

export interface CriterionScore { name: string; score: number; comment: string }
export interface QuestionFeedback {
  question: string;
  answer_summary: string;
  relevance: number;
  correctness: number;
  clarity_structure: number;
  completeness: number;
  objective_errors: string[];
  skipped?: boolean;
  difficulty?: string;
  subjective_feedback: string[];
  strengths: string[];
  improvements: string[];
  improved_answer: string;
}
export interface Report {
  error?: string;
  error_kind?: "empty";
  overall_score: number;
  overall_summary: string;
  criteria: CriterionScore[];
  questions: QuestionFeedback[];
  strengths: string[];
  areas_to_improve: string[];
  preparation_plan: { topic: string; why: string; how_to_practise: string }[];
  evidence_note: string;
  category_label?: string;
  minutes?: number;
  end_reason?: string;
  saved?: boolean;
  session_id?: string;
  profile?: CoachState["profile"];
  question_log?: QuestionEntry[];
  kind?: "interview" | "practice";
  confidence?: "high" | "medium" | "low";
  focus?: Focus | null;
}

/** One question the coach asked, with the user's answer (Questions tab/page). */
export interface QuestionEntry {
  phase: "practice" | "interview";
  question: string;
  answer: string;
  feedback: string;
  improved_answer?: string;
  improvements?: string[];
  answer_summary?: string;
}

export type Verdict = "strong" | "good" | "partly" | "needs_work" | "not_answered";

export interface WorksheetItem extends QuestionEntry {
  verdict?: Verdict;
  assessment?: string;
  model_answer?: string;
  key_points?: string[];
}

export interface WorksheetData {
  session: HistoryItem & { kind: "interview" | "practice" };
  items: WorksheetItem[];
  pending?: boolean; // model answers still being written
  error: string;
}

export interface QuestionSession extends HistoryItem {
  kind: "interview" | "practice";
  questions: QuestionEntry[];
}

export interface Settings {
  avatar_mode: "3d" | "video";
  language: string;
  voice: string;
  avatar_id: string;
  avatar_name: string;
  avatar_sandbox: boolean;
  speed: "fast" | "balanced" | "patient";
  video_quality: string;
  save_history_default: boolean;
  options: { voices: Record<string, string>; languages: string[]; speeds: string[]; qualities: string[] };
}

export interface AvatarInfo { id: string; name: string; preview_url: string | null; is_1080p: boolean; sandbox: boolean }

export interface HistoryItem {
  id: string;
  created_at: number;
  interview_type: string;
  role: string;
  experience_level: string;
  category: string;
  minutes: number;
  end_reason: string;
  overall_score: number | null;
}

/* ---------- Preparation Studio, Progress, Resume match ---------- */

export interface Focus {
  topic: string;
  kind: "weakness" | "recommendation" | "reassess" | "resume" | "studio";
  questions?: string[];
  notes?: string;
  interview_type?: string;
  role?: string;
  level?: string;
}

export type DiagramKind = "mindmap" | "concept" | "flowchart" | "skillgap" | "star" | "roadmap";

export interface DNode {
  id: string;
  label: string;
  detail: string;
  role: string;
  evidence?: string;
  questions?: string[];
  note?: string;
  status?: "pending" | "in_progress" | "done";
  importance?: string;
}
export interface DEdge { source: string; target: string; label?: string }
/** A diagram the coach draws during a live session. */
export interface LiveDiagram { id: string; status: "pending" | "ready" | "error"; topic: string; kind: DiagramKind; saved?: boolean; diagram?: DiagramData; error?: string }
export interface DiagramData { kind: DiagramKind; title: string; summary: string; nodes: DNode[]; edges: DEdge[] }

export interface Weakness {
  id: string; topic: string;
  kind: "knowledge_gap" | "incomplete_answer" | "weak_examples" | "unclear_communication" | "lacks_structure";
  severity: "high" | "medium" | "low"; evidence: string; occurrences: number; why_it_matters: string;
  revision_note: string; framework: string; practice_questions: string[];
}
export interface InsightsData {
  summary: string;
  weaknesses: Weakness[];
  strengths: { topic: string; evidence: string }[];
  recommendations: { title: string; why: string; action: "practice" | "study" | "diagram"; topic: string }[];
  reassessment: { topic: string; status: "improved" | "still_weak" | "not_reassessed"; evidence: string }[];
}

export interface StudyPackData {
  title: string; topic: string;
  notes: { heading: string; body: string }[];
  definitions: { term: string; meaning: string }[];
  question_bank: { question: string; type: string; difficulty: string; model_answer: string; key_points: string[] }[];
  quiz: { question: string; options: string[]; answer_index: number; explanation: string }[];
  flashcards: { front: string; back: string }[];
  frameworks: { name: string; steps: { name: string; guidance: string }[]; example: string }[];
  checklist: string[];
}

export interface SkillRow {
  skill: string; importance: "required" | "preferred"; status: "demonstrated" | "partial" | "not_mentioned";
  evidence_quote: string; evidence_verified: boolean; note: string;
}
export interface ResumeMatchData {
  role_title: string; summary: string; skills: SkillRow[];
  counts: Record<SkillRow["status"], number>;
  questions: { technical: string[]; behavioral: string[]; resume_followups: string[] };
  talking_points: { project: string; how_to_explain: string }[];
  roadmap: { step: string; why: string; related_skill: string }[];
  diagram: DiagramData; caveat: string;
}

export interface Material<T = unknown> {
  id: string; created_at: number; updated_at?: number;
  kind: "insights" | "diagram" | "studypack" | "resume_match";
  title: string; source: Record<string, unknown>; data: T;
}

export interface ProgressPoint { date: string; created_at: number; score: number; session_id?: string; id?: string }
export interface CategoryProgress {
  category: string; label: string;
  sessions: (ProgressPoint & { id: string; interview_type: string; role: string })[];
  trend: { enough_data: boolean; count: number; first?: number; latest?: number; change?: number; average?: number };
  criteria: { name: string; points: ProgressPoint[]; average: number; latest: number; assessed: number; change?: number }[];
  repeated_weaknesses: { name: string; times_weak: number; assessed: number; latest: number }[];
  strengths: { name: string; average: number; assessed: number }[];
  improved: { name: string; from: number; to: number }[];
  needs_reassessment: { name: string; latest: number; reason: string }[];
}
export interface ProgressData {
  categories: CategoryProgress[];
  activity: { week: string; interviews: number; practice: number }[];
  timeline: { id: string; date: string; kind: "interview" | "practice"; title: string; category: string; score: number | null; focus: string }[];
  totals: { sessions: number; interviews: number; practice: number };
  filters: { categories: { id: string; label: string }[]; roles: string[] };
}

export interface AssistantMessage { role: "user" | "assistant"; text: string; action?: AssistantAction }
export interface AssistantAction { action: "none" | "diagram" | "practice" | "studypack"; action_topic: string; diagram_kind: DiagramKind }
export interface AssistantContext { type: "report" | "material" | "insights" | "general"; id?: string; node_id?: string; label?: string }
