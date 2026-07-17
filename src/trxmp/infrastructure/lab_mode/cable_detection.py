"""Finding a virtual audio cable's capture endpoint.

Only VB-Audio's VB-CABLE is matched today (by its exact, stable device
name — "CABLE Output (VB-Audio Virtual Cable)"), the same "one thing,
verified" scoping this project has favoured all along rather than
guessing at every virtual-cable product's naming. Adding a second
vendor later is one more entry in ``_CAPTURE_NAME_PATTERNS``, not an
architecture change.

WASAPI specifically, matching every other capture path in this app
(the M7 spectrum analyzer's loopback, this pipeline's render side): it's
the modern, lowest-overhead Windows audio API, and mixing host APIs
within one pipeline invites format mismatches for no benefit.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

if sys.platform == "win32":
    import pyaudiowpatch as pyaudio

# VB-Audio's stable, documented device name for CABLE's recording side —
# what apps sent to "CABLE Input" mirror onto, and what Trxmp captures
# from. Matched case-insensitively as a substring, since Windows
# sometimes truncates the trailing "(VB-Audio Virtual Cable)" in device
# listings depending on driver version and display context.
_CAPTURE_NAME_PATTERNS = ("cable output",)
_PLAYBACK_NAME_PATTERNS = ("cable input",)


@dataclass(frozen=True, slots=True)
class VirtualCable:
    """A virtual cable's two matched endpoints, ready to open."""

    capture_device_index: int
    capture_device_name: str
    sample_rate: int
    channels: int
    playback_device_name: str | None  # the name to tell the user to route into


def detect_virtual_cable() -> VirtualCable | None:
    """The first recognised virtual cable, or None if none is installed."""
    if sys.platform != "win32":
        return None
    try:
        with pyaudio.PyAudio() as audio:
            wasapi_index = audio.get_host_api_info_by_type(pyaudio.paWASAPI)["index"]
            # PyAudioWPatch ships no type stubs, so a device-info dict is
            # genuinely `Any` — contained here at the boundary rather
            # than let loose, the same move made for scipy/pycaw.
            capture: dict[str, Any] | None = None
            playback_name: str | None = None
            for index in range(audio.get_device_count()):
                info = audio.get_device_info_by_index(index)
                if info["hostApi"] != wasapi_index:
                    continue
                name = str(info["name"]).lower()
                if (
                    capture is None
                    and info["maxInputChannels"] > 0
                    and any(pattern in name for pattern in _CAPTURE_NAME_PATTERNS)
                ):
                    capture = info
                if (
                    playback_name is None
                    and info["maxOutputChannels"] > 0
                    and any(pattern in name for pattern in _PLAYBACK_NAME_PATTERNS)
                ):
                    playback_name = str(info["name"])
            if capture is None:
                return None
            return VirtualCable(
                capture_device_index=int(capture["index"]),
                capture_device_name=str(capture["name"]),
                sample_rate=int(capture["defaultSampleRate"]),
                channels=int(capture["maxInputChannels"]),
                playback_device_name=playback_name,
            )
    except Exception:
        # PortAudio/COM enumeration can fail in many undocumented ways
        # (a driver mid-reinstall, a device vanishing mid-scan); "no
        # cable detected" is the only sane answer to any of them.
        return None


def select_render_device() -> int | None:
    """A real (non-virtual-cable) output device to render Lab mode's
    processed audio to, or None if nothing suitable was found.

    This is *not* "whatever Windows calls the default output" — using
    Lab mode at all means the user has set their Windows default output
    to the cable's playback side (``CABLE Input``), specifically so apps
    route *into* Trxmp. Asking for "the default" at that point would
    return the cable itself, and rendering there would feed Trxmp's own
    output straight back into its own input: a feedback loop, not audio.
    So instead this looks for the first real WASAPI output device that
    *isn't* part of a virtual cable, preferring whichever one Windows
    considers default among those.
    """
    if sys.platform != "win32":
        return None
    try:
        with pyaudio.PyAudio() as audio:
            wasapi = audio.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_index = int(wasapi["defaultOutputDevice"])
            default_info = audio.get_device_info_by_index(default_index)
            if not _is_virtual_cable(str(default_info["name"])):
                return default_index

            for index in range(audio.get_device_count()):
                info = audio.get_device_info_by_index(index)
                if (
                    info["hostApi"] == wasapi["index"]
                    and info["maxOutputChannels"] > 0
                    and not _is_virtual_cable(str(info["name"]))
                ):
                    return int(info["index"])
            return None
    except Exception:
        return None


def _is_virtual_cable(name: str) -> bool:
    lowered = name.lower()
    return "cable" in lowered or "loopback" in lowered
