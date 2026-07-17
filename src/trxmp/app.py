"""Application bootstrap — the composition root.

This is the only module allowed to know about every layer at once: it
constructs the objects, wires them together, and hands control to Qt.
Keeping all wiring in one place is what lets every other module stay
ignorant of how its collaborators are built (the essence of dependency
injection, with or without a framework).

Concretely: this is where the abstract becomes concrete. ``MainWindow``
asks for "a preset library" and "a preferences store"; only these few
lines know that means SQLite and a JSON file. Swapping either — for a
test double, or for a future sync backend — changes this file and
nothing else.
"""

import sys

from PySide6.QtWidgets import QApplication

from trxmp import __version__
from trxmp.application.preset_library import PresetLibrary
from trxmp.infrastructure.database import create_default_engine
from trxmp.infrastructure.paths import data_dir
from trxmp.infrastructure.preferences_file import PREFERENCES_FILENAME, JsonPreferencesStore
from trxmp.infrastructure.preset_repository import SqlitePresetRepository
from trxmp.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Trxmp")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Equix")

    library = PresetLibrary(SqlitePresetRepository(create_default_engine()))
    preferences_store = JsonPreferencesStore(data_dir() / PREFERENCES_FILENAME)

    window = MainWindow(library=library, preferences_store=preferences_store)
    window.show()
    return app.exec()
