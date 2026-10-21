import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { useCoachRoom } from "./useCoachRoom";
import type { AssistantAction, AssistantContext, Focus, Report, Settings } from "./types";
import Welcome from "./screens/Welcome";
import RoomScreen from "./screens/Room";
import ResultsScreen, { type ReportActions } from "./screens/Results";
import HistoryScreen from "./screens/History";
import SettingsScreen from "./screens/Settings";
import WorksheetsScreen from "./screens/Questions";
import WorksheetScreen from "./screens/Worksheet";
import type { StudioRequest } from "./screens/Studio";
import { loadAvatar } from "./avatarEngine";

// The bigger new pages load only when opened, so the app starts fast.
const ProgressScreen = lazy(() => import("./screens/Progress"));
const StudioScreen = lazy(() => import("./screens/Studio"));
const ResumeMatchScreen = lazy(() => import("./screens/ResumeMatch"));
const Assistant = lazy(() => import("./components/Assistant"));

type Tab = "practice" | "progress" | "studio" | "resume" | "questions" | "history" | "settings";
const TABS: { id: Tab; label: string }[] = [
  { id: "practice", label: "Practice" },
  { id: "progress", label: "Progress" },
  { id: "studio", label: "Studio" },
  { id: "resume", label: "Resume match" },
  { id: "questions", label: "Worksheets" },
  { id: "history", label: "History" },
  { id: "settings", label: "Settings" },
];

function PageLoading() {
  return (
    <div className="skeleton" role="status" aria-live="polite">
      <span className="sk-bar" /><span className="sk-bar short" /><span className="sk-bar" />
      <p className="muted">Loading…</p>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>("practice");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [settingsError, setSettingsError] = useState("");
  const [shownReport, setShownReport] = useState<Report | null>(null);
  const [worksheetId, setWorksheetId] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [studioRequest, setStudioRequest] = useState<StudioRequest | null>(null);
  const [assistant, setAssistant] = useState<AssistantContext | null>(null);
  const room = useCoachRoom();
  const inSession = room.connection === "connecting" || room.connection === "connected" || room.connection === "reconnecting";

  const openWorksheet = (id: string) => {
    setWorksheetId(id);
    setTab("questions");
  };

  useEffect(() => {
    api.settings().then(setSettings).catch((e) => setSettingsError((e as Error).message));
  }, []);

  // Load the 3D interviewer in the background while the user reads the start
  // screen, so she is already on the stage when the coach says hello.
  useEffect(() => {
    if (settings?.avatar_mode === "3d") loadAvatar().catch(() => undefined);
  }, [settings?.avatar_mode]);

  // When the report arrives, show it and leave the room.
  useEffect(() => {
    if (room.report) {
      setShownReport(room.report);
      setFocus(null);
      void room.stop();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [room.report]);

  /** Targeted practice: go to the Practice page with this topic ready to start. */
  const practise = useCallback((f: Focus) => {
    setFocus(f);
    setShownReport(null);
    setTab("practice");
    window.scrollTo({ top: 0 });
  }, []);

  const toStudio = useCallback((req: StudioRequest | null) => {
    setStudioRequest(req);
    setTab("studio");
  }, []);

  const onAssistantAction = (a: AssistantAction) => {
    if (a.action === "practice") practise({ topic: a.action_topic, kind: "studio" });
    else if (a.action === "diagram") toStudio({ type: "diagram", topic: a.action_topic, kind: a.diagram_kind });
    else if (a.action === "studypack") toStudio({ type: "studypack", topic: a.action_topic });
  };

  const reportActions: ReportActions = {
    onPractice: practise,
    onStudio: (r) => toStudio(r),
    onAsk: (ctx) => setAssistant(ctx),
  };

  return (
    <div className={`shell ${assistant ? "with-assistant" : ""}`}>
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <div className="brand" aria-label="Interview Coach">
          <span className="brand-mark" aria-hidden="true" />
          Interview Coach
        </div>
        <nav className="tabs" aria-label="Main">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? "tab active" : "tab"}
              onClick={() => { setTab(t.id); if (t.id === "questions") setWorksheetId(null); }}
              aria-current={tab === t.id ? "page" : undefined}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="content" id="main">
        {inSession && tab !== "practice" && (
          <p className="banner session-banner" role="status">
            <span className="live-dot" aria-hidden="true" />
            Your session is still running.
            <button className="primary" onClick={() => setTab("practice")}>Back to session</button>
          </p>
        )}
        {settingsError && (
          <p className="banner error">
            The app could not reach its local server ({settingsError}). Make sure the coach window is still open.
          </p>
        )}
        <Suspense fallback={<PageLoading />}>
          {tab === "practice" &&
            (inSession ? (
              <RoomScreen room={room} />
            ) : shownReport ? (
              <ResultsScreen report={shownReport} onDone={() => setShownReport(null)} onOpenWorksheet={openWorksheet} actions={reportActions} />
            ) : (
              <Welcome settings={settings} error={room.error} focus={focus} onClearFocus={() => setFocus(null)}
                onStart={(save) => room.start(save, focus)} />
            ))}
          {tab === "progress" && <ProgressScreen onPractice={practise} onStudio={() => toStudio(null)} onOpenWorksheet={openWorksheet} />}
          {tab === "studio" && (
            <StudioScreen onPractice={practise} onAsk={(ctx) => setAssistant(ctx)}
              request={studioRequest} clearRequest={() => setStudioRequest(null)} />
          )}
          {tab === "resume" && <ResumeMatchScreen onPractice={practise} />}
          {tab === "questions" &&
            (worksheetId ? (
              <WorksheetScreen id={worksheetId} onBack={() => setWorksheetId(null)} />
            ) : (
              <WorksheetsScreen onOpen={setWorksheetId} />
            ))}
          {tab === "history" && <HistoryScreen onOpenWorksheet={openWorksheet} actions={reportActions} />}
          {tab === "settings" && <SettingsScreen settings={settings} onSaved={setSettings} />}
        </Suspense>
      </main>

      {assistant && (
        <Suspense fallback={null}>
          <Assistant context={assistant} onClose={() => setAssistant(null)} onAction={onAssistantAction} />
        </Suspense>
      )}
    </div>
  );
}
