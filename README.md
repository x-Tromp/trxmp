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

## Roadmap

- [x] **M0 — Foundations**: tooling, layered skeleton, first DSP slice, minimal window
- [x] **M1 — DSP engine**: full RBJ filter set, cascade response, headroom analysis, limiter, offline WAV processing (`uv run trxmp-dsp process in.wav out.wav --preset smoke-test`)
- [x] **M2 — Domain & persistence**: `StoredPreset` entity, `PresetRepository` Protocol + SQLite/SQLAlchemy adapter, Pydantic-at-the-boundary JSON/YAML/CSV import-export, `trxmp-dsp preset` subcommands
- [ ] **M3 — UI shell**: theme engine (dark/light/accent), interactive EQ curve, band controls
- [ ] **M4 — Equalizer APO backend**: detect install, write configs, live system-wide EQ
- [ ] **M5 — Devices & profiles**: WASAPI device detection, auto profile switching
- [ ] **M6 — Preset ecosystem**: AutoEQ / EQ APO / Peace import, headphone catalog
- [ ] **M7 — Spectrum analyzer**: read-only WASAPI loopback + real-time FFT view
- [ ] **M8 — Lab mode**: pure-Python real-time pipeline via virtual device
- [ ] **M9 — Music knowledge base**: structured audio/production reference database
- [ ] **M10 — Distribution**: packaging, signing, updates, docs
