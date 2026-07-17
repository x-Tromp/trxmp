# Trxmp

A system-wide parametric equalizer and headphone manager for Windows,
built in Python with an Apple-inspired UI.

> Complete redesign of an earlier Tauri/Rust prototype. Not a port — a
> rebuild with layered architecture, milestone-driven development, and
> production-quality tooling from day one.

## Audio architecture

Windows only allows zero-latency system-wide audio processing inside its
audio engine (APO drivers, written in C/C++). Trxmp therefore ships
**two interchangeable audio backends** behind one `AudioBackend`
interface (Strategy pattern):

```
Daily driver (0 ms added):          Lab mode (learning/portfolio):
Apps → Windows Audio Engine         Apps → virtual device (VB-Cable)
        └─ Equalizer APO                    └─ Python DSP pipeline
           ▲ configs written by                (NumPy biquads, ~50 ms)
           Trxmp
```

## Layers

```
src/trxmp/
├── domain/          # business models & rules — pure Python, no I/O
├── dsp/             # filter math & analysis — NumPy only, stateless
├── application/     # use cases — orchestrates domain ↔ infrastructure
├── infrastructure/  # Equalizer APO, WASAPI, SQLite, files — all I/O
└── ui/              # PySide6 — the only layer that may import Qt
```

Dependency direction: `ui → application → domain ← dsp`, with
`infrastructure` implementing interfaces the application layer declares.
`tests/test_architecture.py` parses every module's imports and fails the
build if an arrow points the wrong way.

The UI follows MVVM: `ui/view_models.py` holds session state and emits Qt
signals; the curve and the sliders each bind to it and never to each
other. `app.py` is the composition root — the only place that knows the
preset library means SQLite and preferences mean a JSON file.

## Development

Requires Python ≥ 3.13 and [uv](https://docs.astral.sh/uv/).

```powershell
uv sync                      # create venv + install everything
uv run python -m trxmp       # launch the app
uv run trxmp-dsp --help      # offline DSP + preset library CLI
uv run pytest                # tests
uv run ruff check            # lint
uv run ruff format --check   # formatting
uv run mypy                  # strict type checking
```

All four quality gates must pass before every commit.

### System-wide EQ

Trxmp drives [Equalizer APO](https://sourceforge.net/projects/equalizerapo/)
to equalize everything Windows plays, with no added latency.

```powershell
uv run trxmp-dsp apo status                      # installed? who controls audio?
uv run trxmp-dsp apo apply --preset "Sundara"    # equalize all system audio
uv run trxmp-dsp apo disable                     # bypass, stay connected
uv run trxmp-dsp apo restore                     # hand config.txt back
```

Equalizer APO reads one entry point, `config.txt`, and other tools (Peace,
for one) claim it too. Trxmp keeps its filters in its own `trxmp.txt`,
backs up `config.txt` exactly once before claiming it, never writes
another tool's files, and can hand everything back with `apo restore`.

### Spectrum analyzer

The **Spectrum** toggle overlays a live view of whatever Windows is
playing, drawn behind the EQ curve on the same log-frequency axis. It
reads the default output's WASAPI loopback — capture only, entirely
separate from the EQ path, so it can never affect the sound. When
nothing is playing, WASAPI stops delivering data and the display decays
to silence like a meter falling.

### Devices & profiles

Bind a preset to a device and Trxmp applies it automatically whenever
Windows switches to it — headphones on, your curve is back.

```powershell
uv run trxmp-dsp devices list                                    # outputs, states, profiles
uv run trxmp-dsp devices link --device Arctis --preset "Gaming"  # auto-apply on switch
uv run trxmp-dsp devices unlink --device Arctis
```

`devices list` also flags outputs that Equalizer APO isn't attached to.
APO is installed *per device*, so without that warning the EQ can be on,
the curve set, and nothing happens — the most confusing failure this app
could have.

### Preset library

Presets live in a SQLite database under `%LOCALAPPDATA%\Equix\Trxmp`
and interchange as `.json` / `.yaml` / `.csv`:

```powershell
uv run trxmp-dsp preset import sundara.yaml   # import a shared preset
uv run trxmp-dsp preset list                  # what's in the library
uv run trxmp-dsp preset show "Sundara"        # inspect one preset
uv run trxmp-dsp preset export "Sundara" out.json
uv run trxmp-dsp process in.wav out.wav --preset "Sundara"
```

`preset import` also reads other tools' formats:

| Format | Extension | Notes |
| --- | --- | --- |
| AutoEQ / Equalizer APO | `.txt` | AutoEQ's `ParametricEQ.txt` — one parser, thousands of measured headphone curves |
| Peace | `.peace` | Warns about per-channel EQ and Peace's extra bass boost, which Trxmp can't represent |
| Trxmp | `.json` `.yaml` `.csv` | The native round-trip format |

Imports never silently change how a preset sounds: anything unrepresentable
(a notch filter, an unrecognised Peace filter code) refuses rather than
guessing, and anything imported *smaller* than the file describes prints a
note saying so.

### Knowledge base

A small, honestly-scoped reference database, bundled as YAML rather than
hardcoded — the difference between a data change and a code change when
it's time to extend it:

```powershell
uv run trxmp-dsp reference headphones             # the correction catalog
uv run trxmp-dsp reference headphone hifiman_sundara
uv run trxmp-dsp reference frequency 3500          # "Upper-mids": clarity, harshness
```

The headphone corrections are ported verbatim from the original
Tauri/Rust prototype's correction table — continuing a feature the
earlier app already had, not inventing a new one. None of them are
measurements Trxmp itself has taken (`is_measured` is `false` on every
entry, and `source` says so explicitly); the UI's headphone picker loads
one as a starting-point curve, replacing whatever's currently on the
graph rather than merging into it. The frequency-band vocabulary
(sub-bass through air) is the standard terminology most mixing
references already use.

Deliberately narrower than "every audio-engineering topic" — genres,
mixing technique, room acoustics and the rest of the original spec's
wishlist aren't here. Shipping a small, verifiable slice with a real
extension point (add an entry to the YAML, no code change) beats
fabricating breadth nobody asked Trxmp to vouch for.

## Roadmap

- [x] **M0 — Foundations**: tooling, layered skeleton, first DSP slice, minimal window
- [x] **M1 — DSP engine**: full RBJ filter set, cascade response, headroom analysis, limiter, offline WAV processing (`uv run trxmp-dsp process in.wav out.wav --preset smoke-test`)
- [x] **M2 — Domain & persistence**: `StoredPreset` entity, `PresetRepository` Protocol + SQLite/SQLAlchemy adapter, Pydantic-at-the-boundary JSON/YAML/CSV import-export, `trxmp-dsp preset` subcommands
- [x] **M3 — UI shell**: token-based theme engine (dark/light × 6 accents, persisted), interactive EQ curve (drag = gain + frequency, wheel = Q, double-click = flatten), band controls, preset picker, live gain-staging readout
- [x] **M4 — Equalizer APO backend**: `AudioBackend` Strategy interface, install detection, APO config rendering, live debounced apply, backup/restore of an existing controller's config
- [x] **M5 — Devices & profiles**: Core Audio device detection (pycaw), per-device profiles with automatic preset switching, and a warning when Equalizer APO isn't hooked to the current device
- [x] **M6 — Preset ecosystem**: AutoEQ / Equalizer APO / Peace importers, with warnings for what can't be represented and refusals for what would sound wrong. Verified against a real 40-file Peace collection (40/40)
- [x] **M7 — Spectrum analyzer**: read-only WASAPI loopback (PyAudioWPatch), 96 log-spaced bands at 30 fps drawn behind the EQ curve, instant-attack/timed-release ballistics, follows device switches
- [ ] **M8 — Lab mode**: pure-Python real-time pipeline via virtual device
- [x] **M9 — Music knowledge base**: bundled YAML-backed catalog (frequency-band vocabulary + a 5-headphone correction table ported from the original prototype), `ReferenceCatalog` Protocol, headphone picker in the UI, `trxmp-dsp reference` subcommands. Deliberately scoped narrower than the original wishlist — see the Knowledge base section above
- [ ] **M10 — Distribution**: packaging, signing, updates, docs
