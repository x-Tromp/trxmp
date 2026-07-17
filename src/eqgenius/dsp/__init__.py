"""DSP layer — pure numerical signal processing.

What lives here: filter design, frequency-response math, FFT analysis,
gain staging. Stateless, side-effect-free functions over NumPy arrays.

Rules for this package:
- Depends only on NumPy/SciPy. No Qt, no I/O, no app state.
- Every public function must be deterministic: same inputs, same outputs.
  That property is what makes this the easiest layer to test exhaustively.
"""
