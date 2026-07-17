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
    trxmp-dsp apo status
    trxmp-dsp apo apply --preset "Sundara v2"
    trxmp-dsp apo disable
    trxmp-dsp apo restore
    trxmp-dsp devices list
    trxmp-dsp devices link --device Sundara --preset "Sundara v2"
    trxmp-dsp devices unlink --device Sundara
    trxmp-dsp reference headphones
    trxmp-dsp reference headphone hifiman_sundara
    trxmp-dsp reference frequency 3500
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from trxmp.application.audio_backend import BackendError
from trxmp.application.audio_files import equalize_wav_file
from trxmp.application.devices import ProfileManager
from trxmp.application.preset_library import PresetLibrary
from trxmp.domain.devices import AudioDevice
from trxmp.domain.equalizer import EqBand, EqPreset
from trxmp.domain.errors import DeviceNotFoundError, EqualizerError, HeadphoneNotFoundError
from trxmp.dsp.biquad import FilterType
from trxmp.infrastructure.database import create_default_engine
from trxmp.infrastructure.device_profile_repository import SqliteDeviceProfileRepository
from trxmp.infrastructure.equalizer_apo.backend import EqualizerApoBackend
from trxmp.infrastructure.equalizer_apo.detection import detect_installation
from trxmp.infrastructure.equalizer_apo.device_support import is_apo_enabled_for_device
from trxmp.infrastructure.importers import import_preset_file
from trxmp.infrastructure.preset_files import PresetDocument, save_preset_file
from trxmp.infrastructure.preset_repository import SqlitePresetRepository
from trxmp.infrastructure.reference_data.catalog import YamlReferenceCatalog
from trxmp.infrastructure.windows_audio import PycawDeviceService

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
    imported = import_preset_file(args.file)
    name = args.name or imported.name
    stored = _library().save(name, imported.preset, imported.description, overwrite=args.overwrite)
    print(
        f"imported {stored.name!r} ({len(stored.preset.bands)} bands) from {imported.source_format}"
    )
    # Printed after the success line, not instead of it: the import
    # worked, and these are things the file had that Trxmp doesn't.
    for warning in imported.warnings:
        print(f"  note: {warning}")
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


def _backend() -> EqualizerApoBackend:
    return EqualizerApoBackend(detect_installation())


def _cmd_apo_status(args: argparse.Namespace) -> int:
    installation = detect_installation()
    status = EqualizerApoBackend(installation).status
    print(f"state  : {status.state.value}")
    print(f"detail : {status.detail}")
    if installation is not None:
        print(f"install: {installation.install_path}")
        print(f"config : {installation.config_dir}")
    return 0


def _cmd_apo_apply(args: argparse.Namespace) -> int:
    preset = _resolve_preset(args.preset, _library())
    _backend().apply(preset)
    print(f"applied {args.preset!r} to system audio via Equalizer APO")
    print(f"auto preamp: {preset.safe_preamp_db(_DISPLAY_SAMPLE_RATE):+.2f} dB")
    return 0


def _cmd_apo_disable(args: argparse.Namespace) -> int:
    _backend().disable()
    print("system EQ switched off (Trxmp stays connected)")
    return 0


def _cmd_apo_restore(args: argparse.Namespace) -> int:
    if _backend().restore_previous_config():
        print("restored the Equalizer APO config that was in place before Trxmp")
    else:
        print("nothing to restore — Trxmp never claimed config.txt")
    return 0


def _profile_manager() -> ProfileManager:
    engine = create_default_engine()
    return ProfileManager(SqliteDeviceProfileRepository(engine), _library())


def _find_device(name_fragment: str) -> AudioDevice:
    """Resolve a device by a piece of its name.

    Endpoint IDs are GUIDs — nobody is typing those. Matching a fragment
    of the friendly name is what makes this CLI usable, and refusing an
    ambiguous match is what keeps it honest.
    """
    devices = [
        device
        for device in PycawDeviceService().list_output_devices()
        if device.is_known and name_fragment.lower() in device.name.lower()
    ]
    if not devices:
        raise DeviceNotFoundError(f"no audio output matches {name_fragment!r}")
    if len(devices) > 1:
        names = ", ".join(repr(device.name) for device in devices)
        raise DeviceNotFoundError(f"{name_fragment!r} matches several devices: {names}")
    return devices[0]


def _cmd_devices_list(args: argparse.Namespace) -> int:
    manager = _profile_manager()
    devices = [d for d in PycawDeviceService().list_output_devices() if d.is_known]
    if not devices:
        print("no audio outputs found")
        return 0
    for device in devices:
        marker = "*" if device.is_default else " "
        profile = manager.profile_for(device)
        line = f"{marker} {device.name:<48} [{device.state.value}]"
        if profile is not None:
            line += f"  -> {profile.preset_name}"
        if is_apo_enabled_for_device(device.id) is False:
            line += "  (no Equalizer APO)"
        print(line)
    print("\n* = current default output")
    return 0


def _cmd_devices_link(args: argparse.Namespace) -> int:
    device = _find_device(args.device)
    profile = _profile_manager().bind(device, args.preset)
    print(f"linked {profile.preset_name!r} to {device.name!r}")
    print("it will be applied automatically whenever this device becomes the default")
    return 0


def _cmd_devices_unlink(args: argparse.Namespace) -> int:
    device = _find_device(args.device)
    if _profile_manager().unbind(device):
        print(f"unlinked {device.name!r}")
    else:
        print(f"{device.name!r} had no preset linked")
    return 0


def _cmd_reference_headphones(args: argparse.Namespace) -> int:
    for headphone in YamlReferenceCatalog().list_headphones():
        measured = "measured" if headphone.is_measured else "approximate"
        print(f"{headphone.id:<18} {headphone.name:<30} [{headphone.category.value}, {measured}]")
    return 0


def _cmd_reference_headphone(args: argparse.Namespace) -> int:
    headphone = YamlReferenceCatalog().get_headphone(args.id)
    if headphone is None:
        raise HeadphoneNotFoundError(f"no headphone {args.id!r} in the catalog")
    print(f"name         : {headphone.name}")
    print(f"manufacturer : {headphone.manufacturer}")
    print(f"category     : {headphone.category.value}")
    if headphone.notes:
        print(f"notes        : {headphone.notes}")
    print(f"measured     : {'yes' if headphone.is_measured else 'no — approximate correction'}")
    if headphone.source:
        print(f"source       : {headphone.source}")
    print(f"correction   : {len(headphone.correction)} bands")
    for band in headphone.correction:
        print(
            f"  {band.filter_type.value:<10} {band.frequency_hz:>8.1f} Hz  "
            f"{band.gain_db:+5.1f} dB  Q {band.q:.2f}"
        )
    return 0


def _cmd_reference_frequency(args: argparse.Namespace) -> int:
    band = YamlReferenceCatalog().describe_frequency(args.hz)
    if band is None:
        print(f"{args.hz:g} Hz is outside the catalog's covered range")
        return 0
    print(f"{args.hz:g} Hz falls in {band.name} ({band.low_hz:g}-{band.high_hz:g} Hz)")
    print(band.description)
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

    p_import = actions.add_parser(
        "import",
        help="import a preset (.json/.yaml/.csv, .txt from Equalizer APO or AutoEQ, .peace)",
    )
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

    apo = commands.add_parser("apo", help="drive system-wide EQ via Equalizer APO")
    apo_actions = apo.add_subparsers(dest="apo_action", required=True)

    a_status = apo_actions.add_parser("status", help="is Equalizer APO installed and active?")
    a_status.set_defaults(handler=_cmd_apo_status)

    a_apply = apo_actions.add_parser("apply", help="apply a preset to all system audio")
    a_apply.add_argument("--preset", default="flat", help="builtin or library preset name")
    a_apply.set_defaults(handler=_cmd_apo_apply)

    a_disable = apo_actions.add_parser("disable", help="switch the system EQ off")
    a_disable.set_defaults(handler=_cmd_apo_disable)

    a_restore = apo_actions.add_parser(
        "restore", help="hand config.txt back to whatever controlled it before Trxmp"
    )
    a_restore.set_defaults(handler=_cmd_apo_restore)

    devices = commands.add_parser("devices", help="audio outputs and per-device profiles")
    device_actions = devices.add_subparsers(dest="devices_action", required=True)

    d_list = device_actions.add_parser("list", help="list audio outputs and their profiles")
    d_list.set_defaults(handler=_cmd_devices_list)

    d_link = device_actions.add_parser("link", help="auto-apply a preset for a device")
    d_link.add_argument("--device", required=True, help="part of the device name")
    d_link.add_argument("--preset", required=True, help="library preset name")
    d_link.set_defaults(handler=_cmd_devices_link)

    d_unlink = device_actions.add_parser("unlink", help="forget a device's profile")
    d_unlink.add_argument("--device", required=True, help="part of the device name")
    d_unlink.set_defaults(handler=_cmd_devices_unlink)

    reference = commands.add_parser("reference", help="the bundled audio knowledge base")
    reference_actions = reference.add_subparsers(dest="reference_action", required=True)

    r_headphones = reference_actions.add_parser("headphones", help="list the headphone catalog")
    r_headphones.set_defaults(handler=_cmd_reference_headphones)

    r_headphone = reference_actions.add_parser("headphone", help="show one headphone's correction")
    r_headphone.add_argument("id", help="catalog id, e.g. hifiman_sundara")
    r_headphone.set_defaults(handler=_cmd_reference_headphone)

    r_frequency = reference_actions.add_parser(
        "frequency", help="which named region a frequency falls in"
    )
    r_frequency.add_argument("hz", type=float)
    r_frequency.set_defaults(handler=_cmd_reference_frequency)

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
    except (EqualizerError, BackendError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
