"""
Checks the saved OpenAI key WITHOUT spending money: it only asks OpenAI
which realtime voice models this key can use. Picks the best low-cost one
and saves the choice next to the key. Never prints the key itself.

If the environment variable NEW_OPENAI_API_KEY is set, it is saved first
(other saved keys, such as the Gemini key, are kept).
"""

import os
import pathlib
import sys

from dotenv import load_dotenv, set_key
from openai import APIConnectionError, AuthenticationError, NotFoundError, OpenAI, PermissionDeniedError

APP_DATA = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home())) / "ai-interview-coach"
SECRETS = APP_DATA / "agent.env"

# Preference order: cheapest current model first.
CANDIDATES = ["gpt-realtime-2.1-mini", "gpt-realtime-mini", "gpt-realtime-2.1", "gpt-realtime"]


def main() -> int:
    APP_DATA.mkdir(parents=True, exist_ok=True)
    SECRETS.touch(exist_ok=True)
    new_key = os.environ.get("NEW_OPENAI_API_KEY", "").strip()
    if new_key:
        set_key(str(SECRETS), "OPENAI_API_KEY", new_key, quote_mode="never")
        print("Key saved on this laptop (outside OneDrive).")
    load_dotenv(SECRETS, override=True)
    key = os.getenv("OPENAI_API_KEY", "")
    if not key.startswith("sk-"):
        print("FAIL: the saved key does not look like an OpenAI key (it should start with 'sk-').")
        return 1
    print(f"Key found (length {len(key)}, not shown).")

    client = OpenAI(api_key=key)
    available = []
    for name in CANDIDATES:
        try:
            client.models.retrieve(name)
            available.append(name)
            print(f"  available: {name}")
        except NotFoundError:
            print(f"  not available: {name}")
        except AuthenticationError:
            print("FAIL: OpenAI rejected the key (wrong or deleted key).")
            return 1
        except PermissionDeniedError as e:
            print(f"FAIL: permission denied: {e}")
            return 1
        except APIConnectionError:
            print("FAIL: could not reach OpenAI (internet problem?).")
            return 1

    if not available:
        print("FAIL: this key cannot use any realtime voice model.")
        return 1

    chosen = available[0]
    set_key(str(SECRETS), "OPENAI_REALTIME_MODEL", chosen, quote_mode="never")
    set_key(str(SECRETS), "VOICE_PROVIDER", "openai", quote_mode="never")
    print(f"PASS: key works. Voice model chosen: {chosen}")
    print("Note: this check does not confirm you have credit; the voice test will.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
