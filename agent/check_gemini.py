"""
Saves (optionally) and checks a free Google Gemini API key WITHOUT using any
quota: it only asks Google which models this key can see, then picks a
real-time voice (Live API) model and saves the choice next to the key.
Never prints the key itself.

If the environment variable NEW_GOOGLE_API_KEY is set, it is saved first.
"""

import os
import pathlib
import sys

from dotenv import load_dotenv, set_key
from google import genai
from google.genai import errors

APP_DATA = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home())) / "ai-interview-coach"
SECRETS = APP_DATA / "agent.env"

# Preference order for the real-time voice model.
PREFERRED = [
    "gemini-3.8-live",
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-3.1-flash-live-preview",
]


def main() -> int:
    APP_DATA.mkdir(parents=True, exist_ok=True)
    SECRETS.touch(exist_ok=True)

    new_key = os.environ.get("NEW_GOOGLE_API_KEY", "").strip()
    if new_key:
        set_key(str(SECRETS), "GOOGLE_API_KEY", new_key, quote_mode="never")
        print("Key saved on this laptop (outside OneDrive).")

    load_dotenv(SECRETS, override=True)
    key = os.getenv("GOOGLE_API_KEY", "")
    if not key:
        print("FAIL: no Google API key saved.")
        return 1
    print(f"Key found (length {len(key)}, not shown).")

    client = genai.Client(api_key=key)
    live_models = []
    try:
        for m in client.models.list():
            actions = m.supported_actions or []
            if "bidiGenerateContent" in actions:
                live_models.append((m.name or "").removeprefix("models/"))
    except errors.ClientError as e:
        print(f"FAIL: Google rejected the request ({e.code}). Message: {e.message}")
        return 1
    except Exception as e:  # network problems etc.
        print(f"FAIL: could not reach Google: {type(e).__name__}: {e}")
        return 1

    print("Real-time (Live API) models this key can see:")
    for name in live_models:
        print("  -", name)

    chosen = next((m for m in PREFERRED if m in live_models), live_models[0] if live_models else None)
    if not chosen:
        print("FAIL: this key cannot see any real-time voice model.")
        return 1

    set_key(str(SECRETS), "GEMINI_LIVE_MODEL", chosen, quote_mode="never")
    set_key(str(SECRETS), "VOICE_PROVIDER", "gemini", quote_mode="never")
    print(f"PASS: key works. Voice model chosen: {chosen}")
    print("Note: this check uses no quota. The voice test will confirm real conversation works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
