"""PyInstaller's GUI entry point.

A thin wrapper rather than adding a ``__main__`` guard to
``trxmp/app.py`` itself: the composition root's job is wiring up the
app, not knowing it might one day be frozen. Packaging-specific
bootstrap code lives here, next to the rest of the packaging concerns.
"""

from trxmp.app import main

if __name__ == "__main__":
    raise SystemExit(main())
