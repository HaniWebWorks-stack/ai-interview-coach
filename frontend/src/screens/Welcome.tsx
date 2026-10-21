import { useEffect, useState } from "react";
import { api } from "../api";
import type { Focus, Settings } from "../types";

interface Props {
  settings: Settings | null;
  error: string;
  focus?: Focus | null;
  onClearFocus?: () => void;
  onStart: (saveHistory: boolean) => void;
}

export default function Welcome({ settings, error, focus, onClearFocus, onStart }: Props) {
  const [save, setSave] = useState(false);
  const [starting, setStarting] = useState(false);
  const [credits, setCredits] = useState<number | null>(null);

  useEffect(() => {
    if (settings) setSave(settings.save_history_default);
    if (settings && settings.avatar_mode === "video" && !settings.avatar_sandbox) {
      api.credits().then((d) => setCredits(d.credits_left == null ? null : Number(d.credits_left))).catch(() => setCredits(null));
    }
  }, [settings]);
  const video = settings?.avatar_mode === "video";
  const noCredits = settings && video && !settings.avatar_sandbox && credits !== null && credits < 1;

  const start = () => {
    setStarting(true);
    onStart(save);
  };

  return (
    <section className="welcome">
      {focus && (
        <div className="focus-banner" role="status">
          <div>
            <p className="dg-kicker">{focus.kind === "reassess" ? "Reassessment" : "Targeted practice"}</p>
            <h2>{focus.topic}</h2>
            <p className="muted">
              The coach will skip the getting-to-know-you questions and work on this topic
              {focus.questions?.length ? ` with ${focus.questions.length} prepared question${focus.questions.length === 1 ? "" : "s"}` : ""}.
              {focus.kind === "reassess" ? " It asks first and teaches after, to see how much you now know." : ""}
            </p>
          </div>
          <button className="quiet" onClick={onClearFocus}>Normal session instead</button>
        </div>
      )}
      <div className="welcome-intro">
        <h1>Practise with an interviewer who listens.</h1>
        <p className="lede">
          Tell the coach what you are preparing for. It will help you prepare, and when you say you are
          ready, it runs a 15-minute mock interview and gives you a written report. Talk naturally and
          interrupt whenever you want.
        </p>
        {settings && !video && (
          <p className="muted">
            Your interviewer is a 3D avatar drawn on this computer, speaking {settings.language} with the{" "}
            {settings.voice} voice. It is free and has no time limit: practise for as long as you like.
          </p>
        )}
        {settings && video && (
          <p className="muted">
            Your interviewer is {settings.avatar_name}, speaking {settings.language} with the {settings.voice} voice.{" "}
            {settings.avatar_sandbox
              ? "Wayne is the free test avatar: his video lasts about a minute, then the coach continues by voice."
              : "This avatar uses your LiveAvatar free credits; when they run out the coach continues by voice."}
          </p>
        )}
        {noCredits && (
          <p className="note strong">
            {settings?.avatar_name} has no free credits left this month, so this session will be voice only.
            Choose Wayne in Settings to see a face for about a minute.
          </p>
        )}
      </div>

      <div className="consent card">
        <h2>Before you start</h2>
        <ul className="plain">
          <li>Your browser will ask to use the microphone. Choose <b>Allow</b>.</li>
          <li>
            <b>Use earphones or headphones.</b> With laptop speakers the microphone hears the coach too, and she may
            stop in the middle of a sentence.
          </li>
          <li>
            Your voice goes to Google Gemini to understand and answer you. On Google's free tier, Google may use
            conversations to improve its products, so avoid sharing private personal details.
          </li>
          <li>
            {video
              ? "The avatar video is made by LiveAvatar from the coach's voice."
              : "The 3D interviewer is drawn on this computer from the coach's voice."}{" "}
            Your camera is never used.
          </li>
          <li>No audio is ever recorded or stored.</li>
        </ul>
        <label className="check">
          <input type="checkbox" checked={save} onChange={(e) => setSave(e.target.checked)} />
          <span>
            Save my interview report and transcript on this laptop, so I can see them in History.
            <small> You can delete them at any time.</small>
          </span>
        </label>
        <button className="primary big" onClick={start} disabled={starting && !error}>
          {starting && !error ? "Starting…" : "Start session"}
        </button>
        {error && <p className="error-text" role="alert">{error}</p>}
      </div>
    </section>
  );
}
