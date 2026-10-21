"""
Saves (optionally) and checks your LiveAvatar API key WITHOUT using any
credits: it only asks LiveAvatar how many credits the account has.
Never prints the key. If NEW_LIVEAVATAR_API_KEY is set it is saved first
(other saved keys are kept).
"""

import os
import pathlib
import sys

import requests
from dotenv import load_dotenv, set_key

APP_DATA = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home())) / "ai-interview-coach"
SECRETS = APP_DATA / "agent.env"


def main() -> int:
    APP_DATA.mkdir(parents=True, exist_ok=True)
    SECRETS.touch(exist_ok=True)
    new_key = os.environ.get("NEW_LIVEAVATAR_API_KEY", "").strip()
    if new_key:
        set_key(str(SECRETS), "LIVEAVATAR_API_KEY", new_key, quote_mode="never")
        print("Key saved on this laptop (outside OneDrive).")
    load_dotenv(SECRETS, override=True)
    key = os.getenv("LIVEAVATAR_API_KEY", "")
    if not key:
        print("FAIL: no LiveAvatar key saved.")
        return 1
    print(f"Key found (length {len(key)}, not shown).")
    try:
        r = requests.get(
            "https://api.liveavatar.com/v1/users/credits",
            headers={"X-API-KEY": key, "accept": "application/json"},
            timeout=15,
        )
    except requests.RequestException as e:
        print(f"FAIL: could not reach LiveAvatar: {type(e).__name__}: {e}")
        return 1
    if r.status_code != 200:
        print(f"FAIL: LiveAvatar answered HTTP {r.status_code}: {r.text[:300]}")
        return 1
    data = (r.json() or {}).get("data") or {}
    print(f"PASS: LiveAvatar accepted the key. Credits left: {data.get('credits_left', 'unknown')}")
    print("Note: sandbox (test) sessions use no credits.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
