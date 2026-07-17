"""DSP layer — numerical signal processing.

Two kinds of code live here, with different contracts:

- **Design & analysis functions** (``biquad``): pure and stateless —
  same inputs, same outputs, trivially testable.
- **Streaming processors** (``engine``, ``limiter``): carry *signal*
  state (filter memories, limiter envelope) because IIR filtering is
  inherently stateful across blocks. They still hold no application
  state, do no I/O, and know nothing about presets, files, or Qt.

Rules for this package:
- Depends only on NumPy/SciPy. No Qt, no I/O, no imports from other
  ``eqgenius`` layers — the engine consumes plain coefficients, not
  domain objects, which is what keeps this layer reusable and the
  dependency arrows pointing the right way.
"""
