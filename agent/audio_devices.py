"""Helpers for choosing the microphone and speaker on Windows."""

import sounddevice as sd


def default_hostapi() -> int:
    return sd.query_devices(kind="input")["hostapi"]


def find_device_index(name: str, kind: str) -> int | None:
    """Exact-name match within the default audio system. Indexes can change
    when devices are plugged in or out, so we always look them up by name."""
    channels = "max_input_channels" if kind == "input" else "max_output_channels"
    api = default_hostapi()
    for i, d in enumerate(sd.query_devices()):
        if d["name"] == name and d["hostapi"] == api and d[channels] > 0:
            return i
    return None


def candidate_microphones() -> list[tuple[int, str]]:
    """Default microphone first, then any headset microphones."""
    api = default_hostapi()
    default_in = sd.query_devices(kind="input")
    result = [(sd.default.device[0] if sd.default.device[0] >= 0 else -1, default_in["name"])]
    for i, d in enumerate(sd.query_devices()):
        if d["hostapi"] != api or d["max_input_channels"] <= 0:
            continue
        if "headset" in d["name"].lower() and d["name"] != default_in["name"]:
            result.append((i, d["name"]))
    return result


def matching_output(input_name: str) -> str | None:
    """Finds the headphone output that belongs to a headset microphone."""
    if "(" not in input_name:
        return None
    product = input_name.split("(", 1)[1][:10].lower()
    api = default_hostapi()
    for d in sd.query_devices():
        if d["hostapi"] == api and d["max_output_channels"] > 0 and product in d["name"].lower():
            return d["name"]
    return None
