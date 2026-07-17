"""Offline EQ processor CLI — hear the engine before any GUI exists.

Like ``app.py``, this is a composition root (an *entry point*), so it's
allowed to import from every layer. It stays thin on purpose: parse
arguments, pick a preset, call the application layer, print the report.
If logic ever accumulates here, it's in the wrong place.

Usage:
    uv run eqgenius-dsp input.wav output.wav --preset smoke-test
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from eqgenius.application.audio_files import equalize_wav_file
from eqgenius.domain.equalizer import EqBand, EqPreset
from eqgenius.domain.errors import EqualizerError
from eqgenius.dsp.biquad import FilterType


def _builtin_presets() -> dict[str, EqPreset]:
    return {
        "flat": EqPreset.flat(),
        # Mirrors the original Rust smoke test: deliberately exaggerated
        # (thin + bright) so a working pipeline is unmistakable to the ear.
        "smoke-test": EqPreset(
            bands=(
                EqBand(FilterType.LOW_SHELF, 200.0, -9.0, 0.7),
                EqBand(FilterType.HIGH_SHELF, 6000.0, 6.0, 0.7),
            )
        ),
        "bass-boost": EqPreset(
            bands=(
                EqBand(FilterType.LOW_SHELF, 60.0, 6.0, 0.7),
                EqBand(FilterType.PEAKING, 120.0, 2.0, 1.0),
            )
        ),
        "vocal-clarity": EqPreset(
            bands=(
                EqBand(FilterType.LOW_SHELF, 150.0, -2.0, 0.7),
                EqBand(FilterType.PEAKING, 3000.0, 3.0, 1.2),
                EqBand(FilterType.HIGH_SHELF, 9000.0, 2.0, 0.7),
            )
        ),
    }


def main(argv: list[str] | None = None) -> int:
    presets = _builtin_presets()
    parser = argparse.ArgumentParser(
        prog="eqgenius-dsp",
        description="Equalize a WAV file with the EQ Genius DSP engine.",
    )
    parser.add_argument("input", type=Path, help="input WAV file")
    parser.add_argument("output", type=Path, help="output WAV file (16-bit PCM)")
    parser.add_argument(
        "--preset",
        choices=sorted(presets),
        default="smoke-test",
        help="built-in preset to apply (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 2

    started = time.perf_counter()
    try:
        report = equalize_wav_file(args.input, args.output, presets[args.preset])
    except (EqualizerError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - started

    duration_s = report.num_frames / report.sample_rate
    print(f"preset            : {args.preset}")
    print(
        f"input             : {report.num_channels} ch @ {report.sample_rate} Hz, {duration_s:.1f}s"
    )
    print(f"cascade peak gain : {report.peak_response_db:+.2f} dB")
    print(f"applied preamp    : {report.applied_preamp_db:+.2f} dB (auto headroom)")
    print(f"processed in      : {elapsed:.2f}s ({duration_s / elapsed:.0f}x realtime)")
    print(f"wrote             : {args.output}")
    return 0
