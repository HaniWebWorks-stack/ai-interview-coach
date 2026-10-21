import { useEffect, useRef, useState } from "react";
import { loadAvatar, onAvatarProgress, type AvatarEngine } from "./avatarEngine";

/*
 * The free 3D interviewer on the interview stage. She is loaded in the
 * background as soon as the app opens (avatarEngine.ts); this component moves
 * the ready view onto the stage and drives her behaviour.
 * The coach's voice keeps playing through the normal audio element; a copy of
 * the same sound moves the lips, so the voice never depends on the 3D part.
 * When the coach is interrupted her audio stops, so the mouth closes too.
 */

const PRAISE = /\b(great|excellent|well done|good job|nice|perfect|wonderful|fantastic|good answer)\b/i;

interface Props {
  stream: MediaStream | null;
  speaking: boolean;
  caption: string;
  formal: boolean; // during the mock interview: a calmer, neutral face
  onReady?: () => void; // she is visible: the coach may say hello
}

export default function Avatar3D({ stream, speaking, caption, formal, onReady }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [engine, setEngine] = useState<AvatarEngine | null>(null);
  const [progress, setProgress] = useState(0);
  const [failReason, setFailReason] = useState("");
  const praised = useRef(false);
  const readyCb = useRef(onReady);
  readyCb.current = onReady;

  // Take the (pre)loaded interviewer and put her on the stage.
  useEffect(() => {
    let cancelled = false;
    let taken: AvatarEngine | null = null;
    const stopProgress = onAvatarProgress(setProgress);
    loadAvatar()
      .then((e) => {
        if (cancelled || !box.current) return;
        taken = e;
        Object.assign(e.view.style, { position: "absolute", left: "0", top: "0", width: "100%", height: "100%", visibility: "visible" });
        box.current.appendChild(e.view);
        e.head.start();
        void e.head.audioCtx.resume();
        let greeted = false;
        e.onSentenceStart = () => {
          if (!greeted) {
            greeted = true; // wave hello on the first words of the session
            e.head.lookAtCamera(800);
            e.head.playGesture("handup", 2);
          } else {
            e.head.lookAtCamera(500);
            e.head.speakWithHands();
          }
        };
        setEngine(e);
        readyCb.current?.();
      })
      .catch((err) => !cancelled && setFailReason((err as Error).message || "unknown error"));
    return () => {
      cancelled = true;
      stopProgress();
      if (taken) {
        taken.onSentenceStart = null;
        taken.park(); // keep her loaded for the next session
      }
    };
  }, []);

  // If she could not load, the coach should not wait for her.
  useEffect(() => {
    if (failReason) readyCb.current?.();
  }, [failReason]);

  // Connect the coach's voice to the lip-sync (it is not played from here).
  useEffect(() => {
    if (!engine || !stream) return;
    const src = engine.head.audioCtx.createMediaStreamSource(stream);
    src.connect(engine.lips);
    src.connect(engine.meter);
    return () => src.disconnect();
  }, [engine, stream]);

  // Speaking / listening behaviour.
  useEffect(() => {
    if (!engine) return;
    engine.head.isSpeaking = speaking;
    if (!speaking) {
      praised.current = false;
      engine.head.lookAtCamera(800); // attentive while the user talks
    }
  }, [speaking, engine]);

  // Friendly during coaching, neutral during the mock interview.
  useEffect(() => {
    if (!engine) return;
    try {
      engine.head.setMood(formal ? "neutral" : "happy");
    } catch {
      /* mood not supported by this avatar */
    }
  }, [formal, engine]);

  // A thumbs-up when the coach praises an answer (once per reply).
  useEffect(() => {
    if (!engine || !speaking || praised.current) return;
    if (PRAISE.test(caption)) {
      praised.current = true;
      engine.head.playGesture("thumbup", 2);
    }
  }, [caption, speaking, engine]);

  return (
    <div className="avatar3d">
      <div ref={box} className="avatar3d-canvas" aria-label="Your interviewer" role="img" />
      {!engine && !failReason && (
        <p className="avatar3d-note">
          {progress < 100 ? `Getting your interviewer ready… ${progress ? `${progress}%` : ""}` : "Almost ready…"}
        </p>
      )}
      {failReason && (
        <p className="avatar3d-note">
          The 3D interviewer could not be shown on this computer ({failReason}). The coach still talks normally.
        </p>
      )}
    </div>
  );
}
