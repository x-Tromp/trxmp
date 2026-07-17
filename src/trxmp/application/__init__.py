"""Application layer — use cases and orchestration.

What lives here: services that coordinate the domain and infrastructure
to fulfill user intentions ("apply this preset", "switch profile when the
Arctis connects", "import this AutoEQ file").

Rules for this package:
- Talks to infrastructure through interfaces (Protocols), never concrete
  classes, so backends (Equalizer APO vs. the Python Lab pipeline) stay
  swappable.
- No Qt imports: the UI calls into this layer, never the other way around.
"""
