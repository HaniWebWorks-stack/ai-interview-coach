"""
Voice diagnostic (version 2) - finds out why the AI does not hear you,
using real tests only:

0. Closes any leftover voice-test windows from earlier (they keep using
   the microphone and the free Gemini quota in the background).
1. Microphone test: records 5 seconds from the laptop microphone and from
   any headset microphone, and measures how loud each one was.
   Nothing is saved except the loudness numbers.
2. Gemini connection test: sends a short TYPED message to each free voice
   model and checks it speaks back (proves the key + model work).
3. Gemini hearing test: sends your loudest recording and checks whether the
   model heard your words and replied.

Uses a small amount of free Gemini quota. Costs nothing.
Results: logs/diagnose-report.txt  (the key is never written anywhere).
The best microphone, speaker and model are saved for the voice test.
"""

import asyncio
import datetime
import os
import pathlib
import sys
import time

import numpy as np
import psutil
import sounddevice as sd
from dotenv import load_dotenv, set_key
from google import genai
from google.genai import types

from audio_devices import candidate_microphones, matching_output

APP_DATA = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home())) / "ai-interview-coach"
SECRETS = APP_DATA / "agent.env"
PROJECT_DIR = pathlib.Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_DIR / "logs"
REPORT = LOG_DIR / "diagnose-report.txt"

LANGUAGE = "en-US"  # tells Gemini to expect English speech
EXPECTED_WORDS = {"hello", "hear", "preparing", "sales", "manager", "interview"}
RATE = 16000  # Gemini Live expects 16 kHz, 16-bit, mono audio input
SECONDS = 5
SILENT_PEAK = 1000   # below this: basically silent
QUIET_PEAK = 6000    # below this: probably too quiet for speech detection

MODELS = [
    "gemini-3.8-live",
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-3.1-flash-live-preview",
]

lines: list[str] = []


def say(msg: str = "") -> None:
    print(msg)
    lines.append(msg)


def close_leftover_voice_tests() -> None:
    say("== 0. Leftover voice tests ==")
    me = os.getpid()
    closed = 0
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            if p.info["pid"] == me:
                continue
            cmd = " ".join(p.info["cmdline"] or []).lower()
            if "agent.py" not in cmd or "console" not in cmd:
                continue
            where = cmd
            try:
                where += " " + p.cwd().lower()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass
            if "ai-interview-coach" in where:
                for child in p.children(recursive=True):
                    child.terminate()
                p.terminate()
                closed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if closed:
        time.sleep(2)
    say(f"Closed {closed} leftover voice test(s).")


def record(device: int, name: str) -> tuple[bytes, int] | None:
    print()
    print(f"Next microphone: {name}")
    print("Get ready to speak...")
    for n in (3, 2, 1):
        print(f"  {n}")
        time.sleep(1)
    print(">>> RECORDING NOW - say in English: 'Hello, can you hear me?")
    print(">>> I am preparing for a sales manager interview.'  (5 seconds)")
    try:
        audio = sd.rec(
            int(SECONDS * RATE), samplerate=RATE, channels=1, dtype="int16",
            device=None if device < 0 else device,
        )
        sd.wait()
    except Exception as e:
        say(f"  {name}: could not record ({type(e).__name__}: {e})")
        return None
    print(">>> Recording finished.")
    samples = audio[:, 0]
    peak = int(np.abs(samples.astype(np.int32)).max())
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    verdict = "SILENT" if peak < SILENT_PEAK else ("QUIET" if peak < QUIET_PEAK else "GOOD")
    say(f"  {name}: peak={peak} / 32767, average={rms:.0f}  -> {verdict}")
    return samples.tobytes(), peak


async def talk_to_model(client: genai.Client, model: str, pcm: bytes | None) -> dict:
    """Returns what happened: connected, heard, said, audio bytes, error."""
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction="You are a friendly interview coach. Reply in one short English sentence.",
        speech_config=types.SpeechConfig(language_code=LANGUAGE),
    )
    r = {"connected": False, "heard": "", "said": "", "audio": 0, "error": ""}

    async def run() -> None:
        async with client.aio.live.connect(model=model, config=config) as session:
            r["connected"] = True

            async def sender() -> None:
                if pcm is None:
                    await session.send_realtime_input(text="Hello! Please say one short sentence to greet me.")
                    return
                chunk = RATE // 10 * 2  # 100 ms of 16-bit audio
                for i in range(0, len(pcm), chunk):
                    await session.send_realtime_input(
                        audio=types.Blob(data=pcm[i : i + chunk], mime_type="audio/pcm;rate=16000"))
                    await asyncio.sleep(0.1)
                silence = bytes(chunk)
                for _ in range(20):  # 2 s of silence so the model knows you finished
                    await session.send_realtime_input(
                        audio=types.Blob(data=silence, mime_type="audio/pcm;rate=16000"))
                    await asyncio.sleep(0.1)

            send_task = asyncio.create_task(sender())
            try:
                while True:
                    got_any = False
                    async for msg in session.receive():
                        got_any = True
                        sc = msg.server_content
                        if not sc:
                            continue
                        if sc.input_transcription and sc.input_transcription.text:
                            r["heard"] += sc.input_transcription.text
                        if sc.output_transcription and sc.output_transcription.text:
                            r["said"] += sc.output_transcription.text
                        if sc.model_turn and sc.model_turn.parts:
                            for part in sc.model_turn.parts:
                                if part.inline_data and part.inline_data.data:
                                    r["audio"] += len(part.inline_data.data)
                        if sc.turn_complete and r["audio"]:
                            return
                    if not got_any:
                        r["error"] = "Google closed the connection"
                        return
            finally:
                send_task.cancel()

    try:
        await asyncio.wait_for(run(), timeout=30)
    except asyncio.TimeoutError:
        r["error"] = "no reply within 30 seconds"
    except Exception as e:
        r["error"] = f"{type(e).__name__}: {e}"
    return r


def show(r: dict, with_hearing: bool) -> bool:
    say(f"   connected to Google: {'yes' if r['connected'] else 'no'}")
    if with_hearing:
        say(f"   model heard: {r['heard'].strip()!r}")
    say(f"   model replied: {r['said'].strip()!r}")
    say(f"   reply audio: {r['audio']} bytes")
    if r["error"]:
        say(f"   error: {r['error']}")
    ok = r["audio"] > 0 and not r["error"]
    if with_hearing:
        words = {w.strip(".,?!'\"").lower() for w in r["heard"].split()}
        matched = sorted(words & EXPECTED_WORDS)
        say(f"   your words recognised: {len(matched)} of {len(EXPECTED_WORDS)} {matched}")
        # Passing needs at least 3 of the expected words - a reply alone is not enough.
        ok = ok and len(matched) >= 3
    say("   PASS" if ok else "   FAIL")
    return ok


async def main() -> int:
    LOG_DIR.mkdir(exist_ok=True)
    say(f"Voice diagnostic v3 - {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    load_dotenv(SECRETS, override=True)
    key = os.getenv("GOOGLE_API_KEY", "")
    if not key:
        say("FAIL: no Gemini key saved. Run save-gemini-key.bat first.")
        return 1

    close_leftover_voice_tests()
    say()
    say("== 1. Microphones ==")
    recordings = []
    for index, name in candidate_microphones():
        res = record(index, name)
        if res:
            recordings.append((res[1], name, res[0]))
    say()
    best = max(recordings, default=None, key=lambda x: x[0])
    if best and best[0] >= SILENT_PEAK:
        set_key(str(SECRETS), "VOICE_INPUT_DEVICE", best[1], quote_mode="always")
        out = matching_output(best[1])
        set_key(str(SECRETS), "VOICE_OUTPUT_DEVICE", out or "", quote_mode="always")
        say(f"Chosen microphone: {best[1]} (peak {best[0]})")
        say(f"Chosen speaker: {out or 'Windows default'}")
        if best[0] < QUIET_PEAK:
            say("WARNING: even the best microphone is quiet. Speak closer, or raise the")
            say("microphone level in Windows Sound settings.")
    else:
        say("FAIL: every microphone was silent.")

    client = genai.Client(api_key=key)
    say()
    say("== 2. Gemini connection test (typed message) ==")
    working = []
    for model in MODELS:
        say(f"-- {model}")
        if show(await talk_to_model(client, model, None), with_hearing=False):
            working.append(model)

    say()
    say("== 3. Gemini hearing test (your recorded voice) ==")
    heard_ok = []
    if best and best[0] >= SILENT_PEAK:
        for model in working:
            say(f"-- {model}")
            if show(await talk_to_model(client, model, best[2]), with_hearing=True):
                heard_ok.append(model)
            if heard_ok:
                break
        if not heard_ok:
            say("Your voice reached Google but your words were not understood -")
            say("most likely the microphone is still too quiet.")
    else:
        say("(skipped - no usable microphone recording)")

    say()
    # The model is chosen in agent/settings.env (not changed automatically).
    say(f"RESULT: models that reply: {', '.join(working) or 'none'}")
    say(f"RESULT: models that understood your voice: {', '.join(heard_ok) or 'none'}")
    return 0


if __name__ == "__main__":
    code = 1
    try:
        code = asyncio.run(main())
    finally:
        REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sys.exit(code)
