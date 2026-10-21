import { useCallback, useEffect, useRef, useState } from "react";
import {
  ConnectionState,
  ParticipantKind,
  RemoteParticipant,
  RemoteTrack,
  Room,
  RoomEvent,
  Track,
} from "livekit-client";
import { api } from "./api";
import type { CoachState, Focus, LiveDiagram, QuestionEntry, Report, TranscriptLine } from "./types";

const AVATAR_IDENTITY = "liveavatar-avatar-agent";
const channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("interview-coach-session") : null;

export type AgentVoiceState = "initializing" | "listening" | "thinking" | "speaking" | "idle" | "";

export interface CoachRoom {
  connection: "idle" | "connecting" | "connected" | "reconnecting" | "disconnected";
  error: string;
  micOn: boolean;
  micBlocked: boolean;
  needsAudioClick: boolean;
  coach: CoachState | null;
  agentVoice: AgentVoiceState;
  hasVideo: boolean;
  coachStream: MediaStream | null;
  transcript: TranscriptLine[];
  questions: QuestionEntry[];
  diagrams: LiveDiagram[];
  liveCaption: string;
  notice: string;
  report: Report | null;
  start: (saveHistory: boolean, focus?: Focus | null) => Promise<void>;
  stop: () => Promise<void>;
  toggleMic: () => Promise<void>;
  enableAudio: () => Promise<void>;
  rpc: (method: "coach.pause" | "coach.resume" | "coach.ready" | "coach.end_interview" | "coach.avatar_ready") => Promise<string>;
  attachVideo: (el: HTMLVideoElement | null) => void;
}

function isCoachAgent(p: RemoteParticipant) {
  return p.kind === ParticipantKind.AGENT && p.identity !== AVATAR_IDENTITY;
}

export function useCoachRoom(): CoachRoom {
  const roomRef = useRef<Room | null>(null);
  const videoEl = useRef<HTMLVideoElement | null>(null);
  const videoTrack = useRef<RemoteTrack | null>(null);
  const [connection, setConnection] = useState<CoachRoom["connection"]>("idle");
  const [error, setError] = useState("");
  const [micOn, setMicOn] = useState(false);
  const [micBlocked, setMicBlocked] = useState(false);
  const [needsAudioClick, setNeedsAudioClick] = useState(false);
  const [coach, setCoach] = useState<CoachState | null>(null);
  const [agentVoice, setAgentVoice] = useState<AgentVoiceState>("");
  const [hasVideo, setHasVideo] = useState(false);
  const [coachStream, setCoachStream] = useState<MediaStream | null>(null);
  const [transcript, setTranscript] = useState<TranscriptLine[]>([]);
  const [questions, setQuestions] = useState<QuestionEntry[]>([]);
  const [diagrams, setDiagrams] = useState<LiveDiagram[]>([]);
  const [liveCaption, setLiveCaption] = useState("");
  const [notice, setNotice] = useState("");
  const [report, setReport] = useState<Report | null>(null);

  const readAgentAttributes = useCallback((p: RemoteParticipant) => {
    if (!isCoachAgent(p)) return;
    const raw = p.attributes["coach.state"];
    if (raw) {
      try {
        setCoach(JSON.parse(raw) as CoachState);
      } catch {
        /* ignore malformed */
      }
    }
    const voice = p.attributes["lk.agent.state"];
    if (voice) setAgentVoice(voice as AgentVoiceState);
  }, []);

  const attachVideo = useCallback((el: HTMLVideoElement | null) => {
    videoEl.current = el;
    if (el && videoTrack.current) videoTrack.current.attach(el);
  }, []);

  const cleanup = useCallback(() => {
    videoTrack.current = null;
    setHasVideo(false);
    setCoachStream(null);
    setMicOn(false);
    setAgentVoice("");
    setLiveCaption("");
    document.querySelectorAll("audio[data-coach]").forEach((a) => a.remove());
  }, []);

  const stop = useCallback(async () => {
    const room = roomRef.current;
    roomRef.current = null;
    if (room) await room.disconnect();
    cleanup();
    setConnection("disconnected");
  }, [cleanup]);

  // A new session in another tab ends this one (two sessions = two coaches talking at once).
  useEffect(() => {
    if (!channel) return;
    const onMsg = (ev: MessageEvent) => {
      if (ev.data === "new-session" && roomRef.current) {
        setError("This session ended because a new one started in another tab.");
        void stop();
      }
    };
    channel.addEventListener("message", onMsg);
    return () => channel.removeEventListener("message", onMsg);
  }, [stop]);

  useEffect(() => () => void roomRef.current?.disconnect(), []);

  const start = useCallback(
    async (saveHistory: boolean, focus?: Focus | null) => {
      setError("");
      setReport(null);
      setNotice("");
      setTranscript([]);
      setQuestions([]);
      setDiagrams([]);
      setCoach(null);
      setConnection("connecting");
      channel?.postMessage("new-session");
      try {
        const { url, token } = await api.token(saveHistory, focus);
        const room = new Room({
          adaptiveStream: true,
          dynacast: true,
          audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
        roomRef.current = room;

        room.on(RoomEvent.ConnectionStateChanged, (s: ConnectionState) => {
          const map: Record<string, CoachRoom["connection"]> = {
            connected: "connected",
            connecting: "connecting",
            reconnecting: "reconnecting",
            signalReconnecting: "reconnecting",
            disconnected: "disconnected",
          };
          setConnection(map[s] || "connecting");
        });
        room.on(RoomEvent.Disconnected, () => {
          if (roomRef.current === room) roomRef.current = null;
          cleanup();
          setConnection("disconnected");
        });
        room.on(RoomEvent.MediaDevicesError, (e: Error) => {
          setMicBlocked(true);
          setError(`The microphone could not be used: ${e.message}. Allow microphone access for this page and start again.`);
        });
        room.on(RoomEvent.AudioPlaybackStatusChanged, () => setNeedsAudioClick(!room.canPlaybackAudio));
        room.on(RoomEvent.ParticipantConnected, (p) => readAgentAttributes(p));
        room.on(RoomEvent.ParticipantAttributesChanged, (_changed, p) => {
          if (p instanceof RemoteParticipant) readAgentAttributes(p);
        });
        room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack, _pub, participant: RemoteParticipant) => {
          if (track.kind === Track.Kind.Video) {
            videoTrack.current = track;
            setHasVideo(true);
            if (videoEl.current) track.attach(videoEl.current);
          } else if (track.kind === Track.Kind.Audio) {
            const el = track.attach();
            el.dataset.coach = participant.identity;
            document.body.appendChild(el);
            // The 3D avatar moves its lips from a copy of the coach's voice.
            if (isCoachAgent(participant)) setCoachStream(new MediaStream([track.mediaStreamTrack]));
          }
        });
        room.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
          track.detach().forEach((el) => el.remove());
          if (track.kind === Track.Kind.Audio) {
            setCoachStream((cur) => (cur?.getAudioTracks()[0] === track.mediaStreamTrack ? null : cur));
          }
          if (track === videoTrack.current) {
            videoTrack.current = null;
            setHasVideo(false);
          }
        });

        room.registerTextStreamHandler("coach.transcript", async (reader) => {
          const line = JSON.parse(await reader.readAll()) as TranscriptLine;
          setTranscript((prev) => {
            const i = prev.findIndex((l) => l.id === line.id);
            if (i === -1) return [...prev, line];
            const next = prev.slice();
            next[i] = line; // corrected caption (e.g. Urdu script)
            return next;
          });
        });
        room.registerTextStreamHandler("coach.questions", async (reader) => {
          const msg = JSON.parse(await reader.readAll()) as { questions: QuestionEntry[] };
          setQuestions(msg.questions || []);
        });
        room.registerTextStreamHandler("coach.diagram", async (reader) => {
          const d = JSON.parse(await reader.readAll()) as LiveDiagram;
          setDiagrams((prev) => {
            const i = prev.findIndex((x) => x.id === d.id);
            if (i < 0) return [...prev, d];
            const next = prev.slice();
            next[i] = d;
            return next;
          });
        });
        room.registerTextStreamHandler("coach.notice", async (reader) => {
          const msg = JSON.parse(await reader.readAll()) as { text: string };
          setNotice(msg.text || "");
        });
        room.registerTextStreamHandler("coach.report", async (reader) => {
          setReport(JSON.parse(await reader.readAll()) as Report);
        });
        // Live words of the coach while it speaks (synchronised to the voice).
        room.registerTextStreamHandler("lk.transcription", async (reader, info) => {
          const sender = room.remoteParticipants.get(info.identity);
          const micSid = room.localParticipant.getTrackPublication(Track.Source.Microphone)?.trackSid;
          if (reader.info.attributes?.["lk.transcribed_track_id"] === micSid) return; // that's the user
          if (sender && !isCoachAgent(sender) && sender.identity !== AVATAR_IDENTITY) return;
          let text = "";
          for await (const chunk of reader) {
            text += chunk;
            setLiveCaption(text);
          }
        });

        await room.connect(url, token);
        room.remoteParticipants.forEach((p) => readAgentAttributes(p));
        try {
          await room.localParticipant.setMicrophoneEnabled(true);
          setMicOn(true);
          setMicBlocked(false);
        } catch (e) {
          setMicBlocked(true);
          setError(`The microphone could not be used: ${(e as Error).message}`);
        }
        await room.startAudio();
      } catch (e) {
        setError(`Could not start the session: ${(e as Error).message}`);
        await stop();
      }
    },
    [cleanup, readAgentAttributes, stop],
  );

  const toggleMic = useCallback(async () => {
    const room = roomRef.current;
    if (!room) return;
    const next = !room.localParticipant.isMicrophoneEnabled;
    await room.localParticipant.setMicrophoneEnabled(next);
    setMicOn(next);
  }, []);

  const enableAudio = useCallback(async () => {
    await roomRef.current?.startAudio();
    setNeedsAudioClick(false);
  }, []);

  const rpc = useCallback(async (method: Parameters<CoachRoom["rpc"]>[0]) => {
    const room = roomRef.current;
    if (!room) throw new Error("Not connected.");
    const agent = Array.from(room.remoteParticipants.values()).find(isCoachAgent);
    if (!agent) throw new Error("The coach has not joined yet.");
    return room.localParticipant.performRpc({
      destinationIdentity: agent.identity,
      method,
      payload: "",
      responseTimeout: 15000,
    });
  }, []);

  return {
    connection, error, micOn, micBlocked, needsAudioClick, coach, agentVoice, hasVideo, coachStream,
    transcript, questions, diagrams, liveCaption, notice, report, start, stop, toggleMic, enableAudio, rpc, attachVideo,
  };
}
