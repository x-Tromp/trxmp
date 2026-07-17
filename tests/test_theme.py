"""Theme engine tests — no QApplication required.

That these run without Qt at all is the point: the design system is
data plus string generation, so it's testable like any other pure code.
"""

from __future__ import annotations

import re

import pytest

from trxmp.application.preferences import AccentColor, ThemeMode
from trxmp.ui.theme import Palette, Theme, build_palette, build_stylesheet

_HEX = re.compile(r"^#[0-9a-f]{6}$")


@pytest.mark.parametrize("mode", list(ThemeMode))
@pytest.mark.parametrize("accent", list(AccentColor))
def test_every_mode_and_accent_yields_a_complete_valid_palette(
    mode: ThemeMode, accent: AccentColor
) -> None:
    """Guards the combinatorial hole: add an accent and forget its light
    variant, and this fails immediately instead of at runtime with a
    KeyError in front of a user."""
    palette = build_palette(mode, accent)
    for field in Palette.__dataclass_fields__:
        value = getattr(palette, field)
        assert _HEX.match(value), f"{mode}/{accent}: {field} is not a hex colour: {value!r}"


def test_dark_and_light_differ_in_the_ways_that_matter() -> None:
    dark = build_palette(ThemeMode.DARK, AccentColor.BLUE)
    light = build_palette(ThemeMode.LIGHT, AccentColor.BLUE)
    assert dark.background != light.background
    assert dark.text_primary != light.text_primary
    # Light mode uses deeper accents; the vivid dark-mode blue fails
    # contrast on white.
    assert dark.accent != light.accent


def test_dark_background_is_darker_than_its_text_and_light_is_the_reverse() -> None:
    """A crude contrast sanity check — the kind of invariant that
    catches a copy-paste slip between the two palette tables."""
    dark = build_palette(ThemeMode.DARK, AccentColor.GREEN)
    light = build_palette(ThemeMode.LIGHT, AccentColor.GREEN)
    assert _luminance(dark.background) < _luminance(dark.text_primary)
    assert _luminance(light.background) > _luminance(light.text_primary)


def test_stylesheet_embeds_the_selected_accent() -> None:
    theme = Theme(ThemeMode.DARK, AccentColor.PINK)
    stylesheet = theme.stylesheet()
    assert theme.palette.accent in stylesheet
    assert theme.palette.background in stylesheet


def test_stylesheet_has_no_unresolved_placeholders() -> None:
    """f-string typos leave literal braces behind; QSS then silently
    drops the malformed rule and the app looks subtly broken."""
    stylesheet = build_stylesheet(build_palette(ThemeMode.LIGHT, AccentColor.TEAL))
    assert "{}" not in stylesheet
    assert "None" not in stylesheet


def test_theme_mode_toggles_both_ways() -> None:
    assert ThemeMode.DARK.toggled() is ThemeMode.LIGHT
    assert ThemeMode.LIGHT.toggled() is ThemeMode.DARK


def _luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
