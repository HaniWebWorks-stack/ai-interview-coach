/*
 * Loads the free 3D interviewer once, in the background, as soon as the app
 * opens (TalkingHead + HeadAudio, MIT). The interview screen then just moves
 * the ready-made view onto the stage, so she is already there when the coach
 * says hello. The same view is reused for every session.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
const BASE = "/avatar3d/";
const AVATAR = {
  url: `${BASE}avaturn.glb`,
  body: "F",
  avatarMood: "happy",
  baseline: { headRotateX: -0.05, eyeBlinkLeft: 0.15, eyeBlinkRight: 0.15 },
};
// A formal look: dark brown hair, warm studio key light (the page draws a light studio backdrop).
const HAIR_COLOR = "#3a2a22";
const LIGHTS = {
  lightAmbientIntensity: 2,
  lightDirectColor: 0xffeedd,
  lightDirectIntensity: 20,
  lightSpotIntensity: 8,
  lightSpotColor: 0xfff1e0,
};
// Lip-sync tuning: the mouth opens wider on louder syllables and shapes change faster.
const SHAPE_SPEED = 1.5; // 1 = library default (100 ms per shape change)
const LOUDNESS_FLOOR_DB = -50;
const LOUDNESS_RANGE_DB = 35;

export interface AvatarEngine {
  head: any;
  lips: any;
  meter: AnalyserNode;
  view: HTMLDivElement; // the element the 3D view draws into; moved onto the stage
  onSentenceStart: (() => void) | null; // set by the interview screen
  park: () => void; // move the view off-screen again (between sessions)
}

type Progress = (percent: number) => void;

let promise: Promise<AvatarEngine> | null = null;
const listeners = new Set<Progress>();
let lastPercent = 0;

export function onAvatarProgress(fn: Progress): () => void {
  listeners.add(fn);
  fn(lastPercent);
  return () => listeners.delete(fn);
}

function report(p: number) {
  lastPercent = p;
  listeners.forEach((fn) => fn(p));
}

/** Start loading (safe to call many times). */
export function loadAvatar(): Promise<AvatarEngine> {
  if (!promise) {
    promise = create().catch((e) => {
      promise = null; // allow a retry later
      throw e;
    });
  }
  return promise;
}

function parkingSpot(view: HTMLDivElement) {
  // Off-screen but with a real size, so the 3D view can draw and stay ready.
  Object.assign(view.style, {
    position: "fixed", left: "-10000px", top: "0", width: "800px", height: "450px", visibility: "hidden",
  });
  document.body.appendChild(view);
}

async function create(): Promise<AvatarEngine> {
  const [{ TalkingHead }, { HeadAudio }] = await Promise.all([
    import("@met4citizen/talkinghead"),
    import("@met4citizen/headaudio/dist/headaudio.min.mjs"),
  ]);
  const view = document.createElement("div");
  view.className = "avatar3d-canvas";
  parkingSpot(view);

  const h = new TalkingHead(view, {
    ttsEndpoint: "N/A",
    lipsyncModules: [],
    cameraView: "upper",
    cameraDistance: -0.2,
    cameraRotateEnable: false,
    cameraPanEnable: false,
    cameraZoomEnable: false,
    avatarMood: "happy",
    modelFPS: 30, // 60 made the laptop work too hard while the coach was talking
    avatarSpeakingEyeContact: 0.7,
    ...LIGHTS,
  });
  if (import.meta.env.DEV) (window as any).__head = h; // for automated tests

  await h.showAvatar(AVATAR, (ev: ProgressEvent) => {
    if (ev.lengthComputable) report(Math.min(99, Math.round((ev.loaded / ev.total) * 100)));
  });

  // Dark hair looks more formal than the model's auburn.
  h.armature?.traverse((o: any) => {
    if (o.isMesh && /hair/i.test(o.name)) {
      (Array.isArray(o.material) ? o.material : [o.material]).forEach((m: any) => {
        m.color?.set(HAIR_COLOR);
        m.needsUpdate = true;
      });
    }
  });

  // Lip-sync from the coach's voice.
  await h.audioCtx.audioWorklet.addModule(`${BASE}headworklet.min.js`);
  const node = new HeadAudio(h.audioCtx, {
    parameterData: { vadGateActiveDb: -45, vadGateInactiveDb: -60, speakerMeanHz: 220 },
  });
  await node.loadModel(`${BASE}model-en-mixed.bin`);

  // Loudness of the voice, so louder syllables open the mouth wider.
  const meter = h.audioCtx.createAnalyser();
  meter.fftSize = 512;
  const samples = new Float32Array(meter.fftSize);
  let envelope = 0;
  const last = new Array(node.nVisemes).fill(0);
  node.onvalue = null; // values are applied below, scaled by loudness
  h.opt.update = (dt: number) => {
    meter.getFloatTimeDomainData(samples);
    let sum = 0;
    for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
    const db = 20 * Math.log10(Math.sqrt(sum / samples.length) + 1e-9);
    const level = Math.min(1, Math.max(0, (db - LOUDNESS_FLOOR_DB) / LOUDNESS_RANGE_DB));
    envelope += (level - envelope) * (level > envelope ? 0.6 : 0.35); // quick open, softer close
    const gain = 0.15 + 1.15 * envelope;

    node.update(dt * SHAPE_SPEED);
    for (let i = 0; i < node.nVisemes; i++) {
      const a = node.visemeAlphas[i];
      const isSilence = node.visemeNames[i] === "viseme_sil";
      const v = a > 0 ? Math.min(1, node.visemeMaxs[i] * node.easing(a) * (isSilence ? 1 : gain)) : 0;
      if (Math.abs(v - last[i]) > 0.004 || (v === 0 && last[i] !== 0)) {
        const target = h.mtAvatar?.[node.visemeNames[i]];
        if (target) Object.assign(target, { newvalue: v, needsUpdate: true });
        last[i] = v;
      }
    }
  };

  const engine: AvatarEngine = {
    head: h,
    lips: node,
    meter,
    view,
    onSentenceStart: null,
    park: () => {
      parkingSpot(view);
      h.isSpeaking = false;
      h.stop(); // no drawing while off-screen (saves the laptop's battery and fan)
    },
  };
  let lastEnded = 0;
  node.onended = () => {
    lastEnded = Date.now();
  };
  node.onstarted = () => {
    if (Date.now() - lastEnded > 150) engine.onSentenceStart?.();
  };

  // Browsers start audio processing only after a click on the page.
  document.addEventListener("pointerdown", () => {
    if (view.style.visibility !== "hidden") void h.audioCtx.resume();
  });
  document.addEventListener("visibilitychange", () => {
    if (view.style.visibility === "hidden") return; // parked: stays paused
    if (document.visibilityState === "visible") {
      h.start();
      node.start();
    } else {
      node.stop();
      h.stop();
    }
  });

  h.stop(); // parked until the interview screen shows her
  report(100);
  return engine;
}
