"""Trxmp command line — offline processing + preset library management.

Like ``app.py``, this is a composition root (an entry point), so it may
import from every layer; it's also the only place that decides *which*
repository implementation the application services receive. It stays
thin on purpose: parse arguments, wire objects, call one use case,
print the result.

Usage:
    trxmp-dsp process input.wav output.wav --preset bass-boost
    trxmp-dsp preset list
    trxmp-dsp preset import sundara.yaml --name "Sundara v2"
    trxmp-dsp preset export "Sundara v2" sundara.json
    trxmp-dsp preset show "Sundara v2"
    trxmp-dsp preset delete "Sundara v2"
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from trxmp.application.audio_files import equalize_wav_file
from trxmp.application.preset_library import PresetLibrary
from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.domain.errors import EqualizerError
from trxmp.dsp.biquad import FilterType
from trxmp.infrastructure.database import create_default_engine
from trxmp.infrastructure.preset_files import PresetDocument, load_preset_file, save_preset_file
from trxmp.infrastructure.preset_repository import SqlitePresetRepository

_DISPLAY_SAMPLE_RATE = 48_000.0


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


def _library() -> PresetLibrary:
    return PresetLibrary(SqlitePresetRepository(create_default_engine()))


def _resolve_preset(name: str, library: PresetLibrary) -> EqPreset:
    """Library presets first (users may shadow builtins), then builtins."""
    try:
        return library.get(name).preset
    except EqualizerError:
        builtins = _builtin_presets()
        if name in builtins:
            return builtins[name]
        available = ", ".join([*sorted(builtins), *(p.name for p in library.list_all())])
        raise EqualizerError(f"unknown preset {name!r}. Available: {available}") from None


def _cmd_process(args: argparse.Namespace) -> int:
    if not args.input.is_file():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 2
    preset = _resolve_preset(args.preset, _library())

    started = time.perf_counter()
    report = equalize_wav_file(args.input, args.output, preset)
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


def _cmd_preset_list(args: argparse.Namespace) -> int:
    stored = _library().list_all()
    if not stored:
        print("library is empty — import one with: trxmp-dsp preset import <file>")
    for item in stored:
        bands = len(item.preset.bands)
        updated = item.updated_at.strftime("%Y-%m-%d %H:%M")
        description = f"  — {item.description}" if item.description else ""
        print(f"{item.name:<30} {bands:>2} bands  updated {updated}{description}")
    print(f"\nbuiltins: {', '.join(sorted(_builtin_presets()))}")
    return 0


def _cmd_preset_show(args: argparse.Namespace) -> int:
    stored = _library().get(args.name)
    print(f"name        : {stored.name}")
    if stored.description:
        print(f"description : {stored.description}")
    print(f"preamp      : {stored.preset.requested_preamp_db:+.1f} dB (requested)")
    safe = stored.preset.safe_preamp_db(_DISPLAY_SAMPLE_RATE)
    print(f"safe preamp : {safe:+.2f} dB (computed @ 48 kHz)")
    print(f"bands       : {len(stored.preset.bands)}")
    for band in stored.preset.bands:
        print(
            f"  {band.filter_type.value:<10} {band.frequency_hz:>8.1f} Hz  "
            f"{band.gain_db:+5.1f} dB  Q {band.q:.2f}"
        )
    return 0


def _cmd_preset_import(args: argparse.Namespace) -> int:
    if not args.file.is_file():
        print(f"error: file not found: {args.file}", file=sys.stderr)
        return 2
    document = load_preset_file(args.file)
    name = args.name or document.name
    stored = _library().save(
        name, document.to_domain(), document.description, overwrite=args.overwrite
    )
    print(f"imported {stored.name!r} ({len(stored.preset.bands)} bands)")
    return 0


def _cmd_preset_export(args: argparse.Namespace) -> int:
    stored = _library().get(args.name)
    document = PresetDocument.from_domain(stored.name, stored.preset, stored.description)
    save_preset_file(args.file, document)
    print(f"exported {stored.name!r} -> {args.file}")
    return 0


def _cmd_preset_delete(args: argparse.Namespace) -> int:
    _library().delete(args.name)
    print(f"deleted {args.name!r}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trxmp-dsp",
        description="Trxmp DSP tools: offline EQ processing and preset library.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    process = commands.add_parser("process", help="equalize a WAV file")
    process.add_argument("input", type=Path, help="input WAV file")
    process.add_argument("output", type=Path, help="output WAV file (16-bit PCM)")
    process.add_argument(
        "--preset",
        default="smoke-test",
        help="builtin or library preset name (default: %(default)s)",
    )
    process.set_defaults(handler=_cmd_process)

    preset = commands.add_parser("preset", help="manage the preset library")
    actions = preset.add_subparsers(dest="action", required=True)

    p_list = actions.add_parser("list", help="list library presets")
    p_list.set_defaults(handler=_cmd_preset_list)

    p_show = actions.add_parser("show", help="show one preset's bands")
    p_show.add_argument("name")
    p_show.set_defaults(handler=_cmd_preset_show)

    p_import = actions.add_parser("import", help="import a .json/.yaml/.csv preset file")
    p_import.add_argument("file", type=Path)
    p_import.add_argument("--name", help="store under this name (default: name in the file)")
    p_import.add_argument("--overwrite", action="store_true", help="replace an existing preset")
    p_import.set_defaults(handler=_cmd_preset_import)

    p_export = actions.add_parser("export", help="export a preset to .json/.yaml/.csv")
    p_export.add_argument("name")
    p_export.add_argument("file", type=Path)
    p_export.set_defaults(handler=_cmd_preset_export)

    p_delete = actions.add_parser("delete", help="delete a library preset")
    p_delete.add_argument("name")
    p_delete.set_defaults(handler=_cmd_preset_delete)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    # argparse.Namespace attributes are untyped (Any); contain it here.
    handler = cast(Callable[[argparse.Namespace], int], args.handler)
    try:
        return handler(args)
    except ValidationError as error:
        print(f"error: the file is not a valid Trxmp preset:\n{error}", file=sys.stderr)
        return 1
    except (EqualizerError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
