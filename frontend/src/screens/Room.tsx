import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { CoachRoom } from "../useCoachRoom";
import type { TimerSnapshot } from "../types";
import Avatar3D from "../Avatar3D";
import QuestionList from "../QuestionList";
import type { LiveDiagram } from "../types";

const DiagramViewer = lazy(() => import("../components/DiagramViewer"));

const KIND_NAME: Record<string, string> = {
  mindmap: "mind map", concept: "concept diagram", flowchart: "flowchart", star: "answer-structure diagram",
};

/** The diagrams the coach draws while she explains, shown under the video. */
function VisualBoard({ diagrams, onHide }: { diagrams: LiveDiagram[]; onHide: () => void }) {
  const [picked, setPicked] = useState<string | null>(null);
  const shown = diagrams.length;
  const lastSeen = useRef(0);
  // A new diagram from the coach comes to the front automatically.
  useEffect(() => {
    if (shown > lastSeen.current) setPicked(null);
    lastSeen.current = shown;
  }, [shown]);
  if (!diagrams.length) return null;
  const cur = diagrams.find((d) => d.id === picked) || diagrams[diagrams.length - 1];
  return (
    <section className="board" aria-label="Diagrams from the coach">
      <div className="board-head">
        <h2>Visual explanation</h2>
        {diagrams.length > 1 && (
          <div className="chips" role="tablist" aria-label="Diagrams in this session">
            {diagrams.map((d) => (
              <button key={d.id} role="tab" aria-selected={d.id === cur.id}
                className={`chip ${d.id === cur.id ? "active" : ""}`} onClick={() => setPicked(d.id)}>
                {d.diagram?.title || d.topic}
              </button>
            ))}
          </div>
        )}
        <button className="quiet board-hide" onClick={onHide} aria-label="Hide the diagram and show only the interviewer">Hide diagram</button>
      </div>
      <div className="board-body">
      {cur.status === "pending" && (
        <div className="board-wait" role="status" aria-live="polite">
          <span className="board-spinner" aria-hidden="true" />
          <p>Drawing a {KIND_NAME[cur.kind] || "diagram"} of <b>{cur.topic}</b>…</p>
          <p className="muted small">It appears here in a few seconds. Keep listening to the coach.</p>
        </div>
      )}
      {cur.status === "error" && <p className="error-text board-wait" role="alert">{cur.error || "The diagram could not be drawn."} You can make it in Studio after the session.</p>}
      {cur.status === "ready" && cur.diagram && (
        <>
          <Suspense fallback={<p className="muted">Opening the diagram…</p>}>
            <DiagramViewer key={cur.id} data={cur.diagram} />
          </Suspense>
          <p className="small muted board-foot">{cur.saved
            ? "Saved in Studio, so you can open it again later. Click any box for details."
            : "Click any box for details. Use Download to keep it (it is saved in Studio only when \"Save my interview report\" is ticked)."}</p>
        </>
      )}
      </div>
    </section>
  );
}

function remainingMs(t: TimerSnapshot | undefined, now: number) {
  if (!t) return 0;
  const elapsed = t.elapsed_ms + (t.running ? now - t.as_of_ms : 0);
  return Math.max(0, t.duration_ms - elapsed);
}

function fmt(ms: number) {
  const s = Math.ceil(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

const VOICE_LABEL: Record<string, string> = {
  speaking: "Speaking",
  listening: "Listening",
  thinking: "Thinking",
  initializing: "Joining",
  idle: "Waiting",
};

export default function RoomScreen({ room }: { room: CoachRoom }) {
  const { coach } = room;
  const [now, setNow] = useState(Date.now());
  const [panel, setPanel] = useState<"plan" | "questions" | "transcript">("plan");
  const [busy, setBusy] = useState("");
  const [actionError, setActionError] = useState("");
  const [confirmEnd, setConfirmEnd] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const [avatarShown, setAvatarShown] = useState(false);
  const toldCoach = useRef(false);
  const [boardOpen, setBoardOpen] = useState(true);
  const diagramCount = room.diagrams.length;
  // Each new diagram from the coach opens the board again, in front.
  useEffect(() => { if (diagramCount > 0) setBoardOpen(true); }, [diagramCount]);

  const phase = coach?.phase;
  const inInterview = phase === "interview";
  const wrapping = phase === "closing" || phase === "evaluating" || phase === "finished";
  const presenting = !inInterview && !wrapping && boardOpen && room.diagrams.length > 0;

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [room.transcript.length, panel]);

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setActionError("");
    try {
      await fn();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  // Tell the coach the 3D interviewer is on screen, so she says hello only then.
  const coachJoined = !!coach;
  useEffect(() => {
    if (!avatarShown || !coachJoined || toldCoach.current) return;
    toldCoach.current = true;
    let tries = 0;
    let timer = 0;
    const send = () => {
      room.rpc("coach.avatar_ready").catch(() => {
        if (++tries < 10) timer = window.setTimeout(send, 1000);
      });
    };
    send();
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [avatarShown, coachJoined]);

  const remaining = remainingMs(coach?.timer, now);
  const avatar = coach?.avatar;
  const voiceState = room.agentVoice ? VOICE_LABEL[room.agentVoice] || room.agentVoice : "Joining";

  let avatarNote = "";
  if (avatar?.status === "starting") avatarNote = "The avatar is joining (up to 20 seconds)…";
  else if (avatar?.status === "unavailable") {
    avatarNote =
      avatar.reason === "no_credits"
        ? `${avatar.name} has no LiveAvatar credits left this month, so the coach is using voice. Choose Wayne in Settings for a free 1-minute face.`
        : avatar.reason === "timeout"
          ? `${avatar.name} didn't appear within 20 seconds, so the coach started by voice.`
          : "The avatar could not start, so the coach is using voice.";
  }
  else if (avatar?.status === "ended") avatarNote = avatar.sandbox
    ? "Wayne's free video minute is over. The coach continues by voice."
    : "The avatar's free credits ran out. The coach continues by voice.";

  return (
    <section className={`room ${presenting ? "presenting" : ""}`}>
      <div className="stage-col">
        <div className={`stage ${room.agentVoice === "speaking" ? "is-speaking" : ""} ${presenting ? "presenting" : ""}`}>
          {presenting && <VisualBoard diagrams={room.diagrams} onHide={() => setBoardOpen(false)} />}
          <div className="stage-person">
          <video ref={room.attachVideo} autoPlay playsInline muted className={room.hasVideo ? "" : "hidden"} />
          {!room.hasVideo && avatar?.status === "3d" && (
            <Avatar3D
              stream={room.coachStream}
              speaking={room.agentVoice === "speaking"}
              caption={room.liveCaption}
              formal={inInterview}
              onReady={() => setAvatarShown(true)}
            />
          )}
          {!room.hasVideo && avatar?.status !== "3d" && (
            <div className="voice-only">
              <span className={`pulse ${room.agentVoice === "speaking" ? "on" : ""}`} aria-hidden="true" />
              <p>{avatar?.status === "starting" ? "Your interviewer is joining…" : "Voice mode"}</p>
            </div>
          )}
          <div className="stage-top">
            <span className={`mode mode-${phase || "joining"}`}>
              {coach ? (coach.paused ? "Paused" : coach.phase_label) : "Connecting"}
            </span>
            {inInterview && (
              <span className={`clock ${remaining <= 60000 ? "low" : ""}`} aria-label={`Time left ${fmt(remaining)}`}>
                {fmt(remaining)}
              </span>
            )}
          </div>
          <div className="stage-bottom">
            <span className="voice-state">{voiceState}</span>
            {room.liveCaption && room.agentVoice === "speaking" && <p className="caption">{room.liveCaption}</p>}
          </div>
          </div>
        </div>

        <div className="status-row" aria-live="polite">
          <span className={`dot ${room.connection === "connected" ? "ok" : "warn"}`}>
            {room.connection === "connected" ? "Connected" : room.connection === "reconnecting" ? "Reconnecting…" : "Connecting…"}
          </span>
          <span className={`dot ${room.micOn ? "ok" : "off"}`}>{room.micBlocked ? "Microphone blocked" : room.micOn ? "Microphone on" : "Microphone muted"}</span>
          {avatar && (
            <span className={`dot ${avatar.status === "on" || avatar.status === "3d" ? "ok" : "off"}`}>
              {avatar.status === "on" ? `${avatar.name} on screen` : avatar.status === "3d" ? "3D interviewer (no time limit)" : "Voice mode"}
            </span>
          )}
        </div>
        {room.notice && <p className="note strong" role="status">{room.notice}</p>}
        {avatarNote && <p className="note">{avatarNote}</p>}

        <div className="controls">
          <button onClick={() => act("mic", room.toggleMic)} disabled={wrapping}>
            {room.micOn ? "Mute microphone" : "Unmute microphone"}
          </button>
          {!inInterview && !wrapping && (
            <button className="primary" disabled={!!busy || !coach} onClick={() => act("ready", () => room.rpc("coach.ready"))}>
              I'm ready for the mock interview
            </button>
          )}
          {!wrapping && coach && (
            <button
              disabled={!!busy}
              onClick={() => act("pause", () => room.rpc(coach.paused ? "coach.resume" : "coach.pause"))}
            >
              {coach.paused ? "Resume" : "Pause"}
            </button>
          )}
          {inInterview && !confirmEnd && (
            <button className="danger" onClick={() => setConfirmEnd(true)}>End interview</button>
          )}
          {inInterview && confirmEnd && (
            <span className="confirm">
              End now and get your report?
              <button className="danger" onClick={() => act("end", () => room.rpc("coach.end_interview"))}>Yes, end</button>
              <button onClick={() => setConfirmEnd(false)}>Keep going</button>
            </span>
          )}
          {!inInterview && (
            <button className="quiet" onClick={() => void room.stop()} disabled={phase === "evaluating"}>
              Leave session
            </button>
          )}
          {!presenting && !inInterview && !wrapping && room.diagrams.length > 0 && (
            <button onClick={() => setBoardOpen(true)}>Show diagrams ({room.diagrams.length})</button>
          )}
          {room.needsAudioClick && <button className="primary" onClick={() => void room.enableAudio()}>Turn on sound</button>}
        </div>
        {phase === "evaluating" && <p className="note strong">Writing your report. This usually takes under a minute.</p>}
        {(actionError || room.error) && <p className="error-text" role="alert">{actionError || room.error}</p>}
      </div>

      <aside className="side">
        <div className="side-tabs" role="tablist">
          <button role="tab" aria-selected={panel === "plan"} className={panel === "plan" ? "active" : ""} onClick={() => setPanel("plan")}>Your plan</button>
          <button role="tab" aria-selected={panel === "questions"} className={panel === "questions" ? "active" : ""} onClick={() => setPanel("questions")}>
            Questions{room.questions.length ? ` (${room.questions.length})` : ""}
          </button>
          <button role="tab" aria-selected={panel === "transcript"} className={panel === "transcript" ? "active" : ""} onClick={() => setPanel("transcript")}>
            Transcript
          </button>
        </div>

        {panel === "plan" ? (
          <div className="plan">
            {!coach?.profile.interview_type ? (
              <p className="muted">
                Answer the coach's questions about the interview you are preparing for. Your plan appears here.
              </p>
            ) : (
              <>
                <dl className="profile">
                  <dt>Interview</dt><dd>{coach.profile.interview_type}</dd>
                  <dt>Role</dt><dd>{coach.profile.role}</dd>
                  <dt>Level</dt><dd>{coach.profile.experience_level}</dd>
                  {coach.profile.goals && (<><dt>Goals</dt><dd>{coach.profile.goals}</dd></>)}
                </dl>
                <h3>Preparation plan</h3>
                {coach.plan.length ? (
                  <ul className="topics">
                    {coach.plan.map((t) => (
                      <li key={t} className={coach.topics_covered.includes(t) ? "done" : ""}>
                        {t}{coach.topics_covered.includes(t) && <span className="sr"> (covered)</span>}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">The coach is putting your plan together.</p>
                )}
                {coach.topics_covered.filter((t) => !coach.plan.includes(t)).length > 0 && (
                  <p className="muted">Also covered: {coach.topics_covered.filter((t) => !coach.plan.includes(t)).join(", ")}</p>
                )}
                {inInterview && <p className="muted">Questions asked so far: {coach.questions_asked}</p>}
              </>
            )}
          </div>
        ) : panel === "questions" ? (
          <div className="side-questions">
            <QuestionList
              items={room.questions}
              emptyText="Questions the coach asks while you practise and in the mock interview appear here. Click one to see your answer."
            />
          </div>
        ) : (
          <div className="transcript" ref={listRef}>
            {room.transcript.length === 0 && <p className="muted">The conversation appears here.</p>}
            {room.transcript.map((l) => (
              <p key={l.id} className={`line ${l.role}`}>
                <span className="who">{l.role === "user" ? "You" : "Coach"}</span>
                {l.text}
                {l.interrupted && <span className="cut"> (interrupted)</span>}
              </p>
            ))}
          </div>
        )}
      </aside>
    </section>
  );
}
