"""The theme engine: design tokens, palettes, and generated stylesheets.

Notice what this module does *not* import: Qt. It turns a
(mode, accent) pair into plain colour strings and a QSS string, which
means the entire design system is unit-testable without spawning a
QApplication — and could feed a future web view or an SVG export
unchanged.

Why tokens instead of hardcoded colours: a design system is a *single
source of truth*. Every surface, border and label in the app resolves to
one of the names below. Changing the dark background is one edit, not a
grep across forty widgets. This is how real design systems (Apple HIG,
Material, Radix) are built, and it's what makes theming possible at all.

Custom-painted widgets (the EQ curve) can't use QSS, so they receive the
:class:`Palette` object directly and paint with the same tokens the
stylesheet uses. One source of truth, two rendering paths.
"""

from __future__ import annotations

from dataclasses import dataclass

from trxmp.application.preferences import AccentColor, ThemeMode

# ── Spacing & radius scale ────────────────────────────────────────────
# A geometric-ish scale rather than arbitrary numbers: consistent rhythm
# is most of what makes a layout feel designed rather than assembled.
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24

RADIUS_SM = 6
RADIUS_MD = 10
RADIUS_LG = 14

# Segoe UI Variable is Windows 11's system font (the closest thing to SF
# Pro on this platform); the rest of the stack keeps the app sane on
# older Windows and other OSes.
FONT_STACK = '"Segoe UI Variable Display", "Segoe UI", system-ui, -apple-system, sans-serif'

FONT_SIZE_CAPTION = 11
FONT_SIZE_BODY = 13
FONT_SIZE_TITLE = 15
FONT_SIZE_DISPLAY = 20


@dataclass(frozen=True, slots=True)
class Palette:
    """Every colour the app is allowed to use, named by role.

    Roles, not hues: widgets ask for ``surface`` or ``text_secondary``,
    never for "#131418". That indirection is what lets the same widget
    code render correctly in dark and light without a single
    conditional.
    """

    background: str
    surface: str
    surface_elevated: str
    surface_hover: str
    border: str
    border_strong: str
    text_primary: str
    text_secondary: str
    text_tertiary: str
    accent: str
    accent_hover: str
    accent_contrast: str
    grid_minor: str
    grid_major: str
    curve_baseline: str


_DARK_BASE = {
    "background": "#0b0c0e",
    "surface": "#131418",
    "surface_elevated": "#1a1c21",
    "surface_hover": "#23252c",
    "border": "#26282e",
    "border_strong": "#34373f",
    "text_primary": "#f5f5f7",
    "text_secondary": "#9a9aa0",
    "text_tertiary": "#65656b",
    "grid_minor": "#1b1d22",
    "grid_major": "#2b2e35",
    "curve_baseline": "#3a3d45",
    "accent_contrast": "#ffffff",
}

_LIGHT_BASE = {
    "background": "#f5f5f7",
    "surface": "#ffffff",
    "surface_elevated": "#ffffff",
    "surface_hover": "#ececf0",
    "border": "#d8d8dd",
    "border_strong": "#bcbcc4",
    "text_primary": "#1d1d1f",
    "text_secondary": "#6e6e73",
    "text_tertiary": "#9a9aa0",
    "grid_minor": "#ececf0",
    "grid_major": "#d5d5db",
    "curve_baseline": "#b8b8c0",
    "accent_contrast": "#ffffff",
}

# (base, hover) per accent per mode. Light-mode accents are darker: the
# same vivid blue that pops on near-black fails contrast on white. This
# table is where accessibility is either won or lost.
_ACCENTS: dict[ThemeMode, dict[AccentColor, tuple[str, str]]] = {
    ThemeMode.DARK: {
        AccentColor.BLUE: ("#0a84ff", "#409cff"),
        AccentColor.GREEN: ("#30d158", "#5ce07d"),
        AccentColor.PURPLE: ("#bf5af3", "#d183f6"),
        AccentColor.ORANGE: ("#ff9f0a", "#ffb84d"),
        AccentColor.PINK: ("#ff375f", "#ff6b88"),
        AccentColor.TEAL: ("#40c8e0", "#6fd8ea"),
    },
    ThemeMode.LIGHT: {
        AccentColor.BLUE: ("#0071e3", "#0058b0"),
        AccentColor.GREEN: ("#248a3d", "#1c6e30"),
        AccentColor.PURPLE: ("#8944ab", "#6d3689"),
        AccentColor.ORANGE: ("#c26100", "#994c00"),
        AccentColor.PINK: ("#d70015", "#a80010"),
        AccentColor.TEAL: ("#0071a4", "#005880"),
    },
}


def build_palette(mode: ThemeMode, accent: AccentColor) -> Palette:
    base = _DARK_BASE if mode is ThemeMode.DARK else _LIGHT_BASE
    accent_hex, accent_hover_hex = _ACCENTS[mode][accent]
    return Palette(accent=accent_hex, accent_hover=accent_hover_hex, **base)


@dataclass(frozen=True, slots=True)
class Theme:
    """A resolved look: one mode, one accent, and everything they imply."""

    mode: ThemeMode = ThemeMode.DARK
    accent: AccentColor = AccentColor.BLUE

    @property
    def palette(self) -> Palette:
        return build_palette(self.mode, self.accent)

    def stylesheet(self) -> str:
        return build_stylesheet(self.palette)


def build_stylesheet(palette: Palette) -> str:
    """Generate the app's QSS from a palette.

    QSS is Qt's CSS-like styling language. Generating it from tokens
    (rather than shipping a static .qss file) is what makes runtime
    theme switching possible: rebuild the string, re-apply, done.
    """
    p = palette
    return f"""
    QWidget {{
        background-color: {p.background};
        color: {p.text_primary};
        font-family: {FONT_STACK};
        font-size: {FONT_SIZE_BODY}px;
    }}

    QLabel {{ background: transparent; }}
    QLabel#brand {{
        font-size: {FONT_SIZE_DISPLAY}px;
        font-weight: 600;
        letter-spacing: 0.5px;
    }}
    QLabel#sectionTitle {{
        font-size: {FONT_SIZE_TITLE}px;
        font-weight: 600;
    }}
    QLabel#caption {{
        color: {p.text_secondary};
        font-size: {FONT_SIZE_CAPTION}px;
    }}
    QLabel#metric {{
        color: {p.text_secondary};
        font-size: {FONT_SIZE_CAPTION}px;
    }}
    QLabel#metricValue {{
        color: {p.text_primary};
        font-size: {FONT_SIZE_CAPTION}px;
        font-weight: 600;
    }}

    QFrame#card {{
        background-color: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS_LG}px;
    }}
    QFrame#separator {{
        background-color: {p.border};
        border: none;
    }}

    QPushButton {{
        background-color: {p.surface_elevated};
        color: {p.text_primary};
        border: 1px solid {p.border};
        border-radius: {RADIUS_SM}px;
        padding: {SPACE_XS}px {SPACE_MD}px;
    }}
    QPushButton:hover {{ background-color: {p.surface_hover}; }}
    QPushButton:pressed {{ border-color: {p.border_strong}; }}
    QPushButton:disabled {{ color: {p.text_tertiary}; }}
    QPushButton#primary {{
        background-color: {p.accent};
        color: {p.accent_contrast};
        border: none;
        font-weight: 600;
    }}
    QPushButton#primary:hover {{ background-color: {p.accent_hover}; }}
    QPushButton#ghost {{
        background: transparent;
        border: none;
        color: {p.text_secondary};
    }}
    QPushButton#ghost:hover {{ color: {p.text_primary}; }}

    QComboBox {{
        background-color: {p.surface_elevated};
        border: 1px solid {p.border};
        border-radius: {RADIUS_SM}px;
        padding: {SPACE_XS}px {SPACE_SM}px;
        min-width: 180px;
    }}
    QComboBox:hover {{ border-color: {p.border_strong}; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{
        background-color: {p.surface_elevated};
        border: 1px solid {p.border};
        border-radius: {RADIUS_SM}px;
        selection-background-color: {p.accent};
        selection-color: {p.accent_contrast};
        outline: none;
        padding: {SPACE_XS}px;
    }}

    QSlider::groove:vertical {{
        background: {p.surface_hover};
        width: 4px;
        border-radius: 2px;
    }}
    QSlider::handle:vertical {{
        background: {p.text_primary};
        border: none;
        height: 14px;
        width: 14px;
        margin: 0 -5px;
        border-radius: 7px;
    }}
    QSlider::handle:vertical:hover {{ background: {p.accent}; }}
    QSlider::handle:vertical:disabled {{ background: {p.text_tertiary}; }}

    QToolTip {{
        background-color: {p.surface_elevated};
        color: {p.text_primary};
        border: 1px solid {p.border};
        border-radius: {RADIUS_SM}px;
        padding: {SPACE_XS}px;
    }}
    """
