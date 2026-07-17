"""Domain layer — the business heart of the application.

What lives here: the concepts the app is *about* — EQ bands, presets,
headphone profiles, devices — and the rules that make them valid.

Rules for this package:
- Pure Python only. No Qt, no audio APIs, no database, no files, no network.
- May depend on ``eqgenius.dsp`` for math, and on nothing else in the app.
- If a module here imports PySide6 or SQLAlchemy, that is a code review failure.

Why: the domain is the part most worth unit-testing and least worth
rewriting when the UI toolkit or storage engine changes.
"""
