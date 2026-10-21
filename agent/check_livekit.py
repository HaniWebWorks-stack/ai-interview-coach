"""
Saves (optionally) and checks your LiveKit Cloud project details WITHOUT
using any minutes: it only asks LiveKit to list the rooms in your project.
Never prints the secret.

New values are read from NEW_LIVEKIT_URL / NEW_LIVEKIT_API_KEY /
NEW_LIVEKIT_API_SECRET if set; other saved keys are kept.
"""

import asyncio
import os
import pathlib
import sys

from dotenv import load_dotenv, set_key
from livekit import api

APP_DATA = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home())) / "ai-interview-coach"
SECRETS = APP_DATA / "agent.env"


def save_new_values() -> None:
    for new, name in (
        ("NEW_LIVEKIT_URL", "LIVEKIT_URL"),
        ("NEW_LIVEKIT_API_KEY", "LIVEKIT_API_KEY"),
        ("NEW_LIVEKIT_API_SECRET", "LIVEKIT_API_SECRET"),
    ):
        value = os.environ.get(new, "").strip()
        if value:
            set_key(str(SECRETS), name, value, quote_mode="never")


async def main() -> int:
    APP_DATA.mkdir(parents=True, exist_ok=True)
    SECRETS.touch(exist_ok=True)
    save_new_values()
    load_dotenv(SECRETS, override=True)

    url = os.getenv("LIVEKIT_URL", "")
    key = os.getenv("LIVEKIT_API_KEY", "")
    secret = os.getenv("LIVEKIT_API_SECRET", "")
    problems = []
    if not url.startswith("wss://"):
        problems.append("the URL should start with wss://")
    if not key.startswith("API"):
        problems.append("the API key should start with API")
    if len(secret) < 20:
        problems.append("the API secret looks too short")
    if problems:
        print("FAIL: " + "; ".join(problems) + ".")
        return 1
    print(f"URL: {url}")
    print(f"API key: {key}")
    print(f"API secret: saved (length {len(secret)}, not shown)")

    lk = api.LiveKitAPI(url=url, api_key=key, api_secret=secret)
    try:
        rooms = await lk.room.list_rooms(api.ListRoomsRequest())
        print(f"PASS: LiveKit accepted the details. Active rooms right now: {len(rooms.rooms)}")
        return 0
    except Exception as e:
        print(f"FAIL: LiveKit did not accept the details: {type(e).__name__}: {e}")
        return 1
    finally:
        await lk.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
