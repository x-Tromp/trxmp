"""Lab mode — the pure-Python real-time pipeline, the second half of the
Strategy pair promised back in M0's README diagram.

Where Equalizer APO (M4) processes audio *inside* the Windows audio
engine and Python only ever writes a config file, Lab mode is the
opposite extreme: capture, DSP, and render all happen in this process,
in Python, on real audio, in real time. It exists for exactly the
reason the README always said it would — learning and portfolio value,
not daily-driver latency — and it's also the first place
:class:`~trxmp.dsp.engine.EqEngine` (built all the way back in M1 and,
until now, only ever run offline against WAV files) finally processes
audio nobody pre-recorded.

The signal path needs a virtual audio cable (VB-Audio VB-CABLE, or
compatible) installed on the machine, because Windows has no built-in
way to hand one process's *output* to another process as an *input*:

    Apps -> CABLE Input (playback)      <- the user sets this as their
              |  (VB-Cable mirrors it)     Windows default output device
              v
    Trxmp captures CABLE Output (recording)
              |
              v  EqEngine.process_block()
              |
    Trxmp renders to a real device (headphones/speakers)

Split by responsibility:
- ``cable_detection``: is a virtual cable installed, and which device
  index is its capture ("Output") side?
- ``pipeline``: the actual capture -> process -> render loop and its
  thread.
- ``backend``: the ``AudioBackend`` implementation wrapping the pipeline,
  the same Strategy interface ``EqualizerApoBackend`` implements.
"""
