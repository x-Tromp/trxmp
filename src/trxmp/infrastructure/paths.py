"""Where Trxmp keeps its data on disk.

On Windows this resolves to ``%LOCALAPPDATA%\\Equix\\Trxmp`` via
``platformdirs`` — the library that encodes each OS's conventions so we
don't hardcode any. The environment override is a deliberate *seam*:
tests point it at a temp directory, and a future portable mode points
it next to the executable, all without touching this code again.
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

ENV_DATA_DIR = "TRXMP_DATA_DIR"

_APP_NAME = "Trxmp"
_APP_AUTHOR = "Equix"


def data_dir() -> Path:
    """The app's data directory, created if missing."""
    override = os.environ.get(ENV_DATA_DIR)
    base = Path(override) if override else Path(user_data_dir(_APP_NAME, _APP_AUTHOR))
    base.mkdir(parents=True, exist_ok=True)
    return base
