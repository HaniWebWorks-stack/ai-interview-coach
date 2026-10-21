import { useEffect, useState } from "react";
import { api } from "../api";
import type { AvatarInfo, Settings } from "../types";

const SPEED_TEXT: Record<string, string> = {
  fast: "Fast: the coach answers after half a second of silence. Best if you speak in full sentences.",
  balanced: "Balanced: waits a little longer before answering.",
  patient: "Patient: waits a full second, so short pauses while you think don't cut you off.",
};

export default function SettingsScreen({ settings, onSaved }: { settings: Settings | null; onSaved: (s: Settings) => void }) {
  const [avatars, setAvatars] = useState<AvatarInfo[] | null>(null);
  const [credits, setCredits] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.avatars().then((d) => setAvatars(d.avatars)).catch((e) => setError(`Avatars could not be loaded: ${(e as Error).message}`));
    api.credits().then((d) => setCredits(d.credits_left)).catch(() => setCredits(null));
  }, []);

  if (!settings) return <p className="muted">Loading settings…</p>;

  const save = async (patch: Partial<Settings>, what: string) => {
    setError("");
    setMessage("");
    try {
      onSaved(await api.saveSettings(patch));
      setMessage(`${what} saved. It applies from your next session.`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const voices = Object.entries(settings.options.voices);
  const sorted = (avatars || []).slice().sort((a, b) => Number(b.sandbox) - Number(a.sandbox) || a.name.localeCompare(b.name));

  return (
    <section className="settings">
      <h1>Settings</h1>
      <p className="muted" role="status">{message}</p>
      {error && <p className="error-text" role="alert">{error}</p>}

      <div className="form-grid">
        <label>
          <span>Interview language</span>
          <select value={settings.language} onChange={(e) => save({ language: e.target.value }, "Language")}>
            {settings.options.languages.map((l) => <option key={l}>{l}</option>)}
          </select>
          <small>With Urdu, your spoken words are shown in Urdu script; with the mix, in Roman Urdu.</small>
        </label>

        <label>
          <span>Coach voice</span>
          <select value={settings.voice} onChange={(e) => save({ voice: e.target.value }, "Voice")}>
            {voices.map(([v, g]) => <option key={v} value={v}>{v} ({g})</option>)}
          </select>
          <small>Choose a voice that matches the avatar.</small>
        </label>

        <label>
          <span>Response speed</span>
          <select value={settings.speed} onChange={(e) => save({ speed: e.target.value as Settings["speed"] }, "Response speed")}>
            <option value="fast">Fast</option>
            <option value="balanced">Balanced</option>
            <option value="patient">Patient</option>
          </select>
          <small>{SPEED_TEXT[settings.speed]}</small>
        </label>

        <label>
          <span>Video avatar quality</span>
          <select value={settings.video_quality} onChange={(e) => save({ video_quality: e.target.value }, "Video quality")}>
            {settings.options.qualities.map((q) => <option key={q}>{q}</option>)}
          </select>
          <small>Only for the video avatar. Lower quality starts slightly faster on slow internet.</small>
        </label>

        <label className="check">
          <input
            type="checkbox"
            checked={settings.save_history_default}
            onChange={(e) => save({ save_history_default: e.target.checked }, "History preference")}
          />
          <span>Tick "save my report" by default on the start screen</span>
        </label>
      </div>

      <h2>Interviewer</h2>
      <div className="mode-choice" role="radiogroup" aria-label="Interviewer type">
        <label className={`mode-option ${settings.avatar_mode === "3d" ? "chosen" : ""}`}>
          <input
            type="radio"
            name="avatar_mode"
            checked={settings.avatar_mode === "3d"}
            onChange={() => save({ avatar_mode: "3d" }, "Interviewer")}
          />
          <span>
            <b>3D interviewer</b> (recommended)
            <small>Free, no time limit. Lip-sync, facial expressions and hand gestures, drawn on this computer.</small>
          </span>
        </label>
        <label className={`mode-option ${settings.avatar_mode === "video" ? "chosen" : ""}`}>
          <input
            type="radio"
            name="avatar_mode"
            checked={settings.avatar_mode === "video"}
            onChange={() => save({ avatar_mode: "video" }, "Interviewer")}
          />
          <span>
            <b>Video avatar</b> (LiveAvatar)
            <small>Looks like a real person, but the free plan gives only about 10 minutes a month.</small>
          </span>
        </label>
      </div>

      {settings.avatar_mode === "video" && (<>
      <h3>Video avatar</h3>
      <p className="muted">
        Current: <b>{settings.avatar_name}</b>. Wayne is free for about a minute per session. Every other avatar uses LiveAvatar
        free-plan credits, 1 per minute{credits != null ? `; ${Number(credits).toFixed(1)} left this month` : ""}. When the
        avatar's time runs out, the coach keeps going by voice.
      </p>
      {!avatars && !error && <p className="muted">Loading avatars…</p>}
      <div className="avatar-grid">
        {sorted.map((a) => (
          <div key={a.id} className={`avatar-card ${a.id === settings.avatar_id ? "chosen" : ""}`}>
            <div className="avatar-media">
              {a.preview_url ? (
                /\.(mp4|webm|mov)(\?|$)/i.test(a.preview_url)
                  ? <video src={a.preview_url} muted loop playsInline preload="metadata" />
                  : <img src={a.preview_url} alt="" loading="lazy" />
              ) : <span>No preview</span>}
            </div>
            <div className="avatar-body">
              <b>{a.name}</b>
              <small>{a.sandbox ? "Free, about 1 minute" : "Uses credits"}</small>
              <button
                className={a.id === settings.avatar_id ? "" : "primary"}
                disabled={a.id === settings.avatar_id}
                onClick={() => save({ avatar_id: a.id }, `Avatar ${a.name}`)}
              >
                {a.id === settings.avatar_id ? "Chosen" : "Choose"}
              </button>
            </div>
          </div>
        ))}
      </div>
      </>)}
    </section>
  );
}
