"""Main application window.

Milestone 0 version: an intentionally minimal dark shell that proves the
Qt toolchain works end to end. The real Apple-inspired UI (theme engine,
EQ curve, sliders) arrives in Milestone 3 — resist the urge to decorate
a skeleton.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget

from eqgenius import __version__


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EQ Genius")
        self.resize(960, 640)
        self.setMinimumSize(720, 480)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        title = QLabel("EQ Genius", central)
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel(f"Milestone 0 · walking skeleton · v{__version__}", central)
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        self.setCentralWidget(central)

        self.setStyleSheet(
            """
            QMainWindow { background-color: #0d0f12; }
            QLabel#title {
                color: #e8eaed;
                font-size: 34px;
                font-weight: 600;
                letter-spacing: 1px;
            }
            QLabel#subtitle {
                color: #6b7280;
                font-size: 13px;
            }
            """
        )
