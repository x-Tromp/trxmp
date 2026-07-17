"""Crash-safe file writing.

Extracted from ``preferences_file`` once a second caller (the Equalizer
APO backend) needed the identical dance. Two copies of a subtle
correctness routine is exactly the duplication worth removing — not
because "DRY", but because a bug fixed in one copy and missed in the
other is how data loss happens.

The naive ``path.write_text(...)`` truncates the file *first*, so a
power cut or crash mid-write leaves a half-written file behind. Writing
to a temporary file and then ``os.replace``-ing it (atomic on Windows
and POSIX alike) means what's on disk is always either the complete old
version or the complete new one — never a corpse in between. That
matters doubly for the APO config, which a live audio driver re-reads
the moment it changes.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_text_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write ``text`` to ``path``, atomically replacing any existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # The temp file must share a filesystem with the target: os.replace is
    # only atomic within one volume, and %TEMP% may well be another drive.
    descriptor, temporary_path = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding=encoding) as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())  # force to the platter before swapping
        os.replace(temporary_path, path)
    except OSError:
        Path(temporary_path).unlink(missing_ok=True)
        raise
