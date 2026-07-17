"""Application bootstrap — the composition root.

This is the only module allowed to know about every layer at once: it
constructs the objects, wires them together, and hands control to Qt.
Keeping all wiring in one place is what lets every other module stay
ignorant of how its collaborators are built (the essence of dependency
injection, with or without a framework).
"""

import sys

from PySide6.QtWidgets import QApplication

from trxmp import __version__
from trxmp.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Trxmp")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Equix")

    window = MainWindow()
    window.show()
    return app.exec()
