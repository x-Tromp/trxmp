"""Infrastructure layer — everything that touches the outside world.

What lives here: Equalizer APO config writing, WASAPI capture, audio
device enumeration, SQLite persistence, file import/export, OS
integration.

Rules for this package:
- Implements the interfaces (Protocols) declared by the application layer.
- This is the only layer allowed to perform I/O.
- Expected to be the hardest layer to unit-test — which is exactly why
  business logic must not leak into it.
"""
