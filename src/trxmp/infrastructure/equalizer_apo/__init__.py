"""Equalizer APO integration — Trxmp's zero-latency system-wide backend.

Equalizer APO is an Audio Processing Object: a driver-level plugin that
Windows loads *inside* its audio engine. Everything the OS plays passes
through it before reaching the hardware, so an EQ applied here costs no
added latency and covers every application at once — Spotify, games,
browsers, system sounds.

Python cannot live in that engine (APOs are C++ DLLs). What Python can
do is decide *what* the EQ should be and hand APO a config file. So the
split is: Trxmp is the brain (UI, presets, headroom analysis, device
profiles), Equalizer APO is the muscle. This package is the seam between
them, and it's deliberately the only place in the codebase that knows
APO's file format exists.

Split across three modules by responsibility:

- ``detection``: is it installed, and where?
- ``config_format``: turning an ``EqPreset`` into APO's syntax (pure
  functions, exhaustively testable without touching a real install)
- ``backend``: the ``AudioBackend`` implementation that writes the files
"""
