"""Shared test configuration.

Qt needs a platform plugin to create widgets. On a CI runner (or any
headless machine) there's no display, so we ask for the "offscreen"
platform *before* anything imports QtGui — Qt reads this at import time,
which is why it can't live inside a fixture.

``setdefault``, not assignment: a developer who wants to watch the tests
drive a real window can run ``QT_QPA_PLATFORM=windows pytest`` and this
gets out of the way.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
