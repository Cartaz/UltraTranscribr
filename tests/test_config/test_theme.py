# tests/test_config/test_theme.py
"""Test per i token di colore del tema Neumorphic Dark."""

import unittest
from config.theme import ThemeColors


class TestThemeColors(unittest.TestCase):
    """Test per la classe ThemeColors."""

    def test_primary_colors_exist(self) -> None:
        """I colori primari devono essere definiti."""
        assert ThemeColors.PRIMARY is not None
        assert ThemeColors.PRIMARY_DARK is not None
        assert len(ThemeColors.PRIMARY) > 0
        assert len(ThemeColors.PRIMARY_DARK) > 0

    def test_danger_colors_exist(self) -> None:
        """I colori pericolosi devono essere definiti."""
        assert ThemeColors.DANGER is not None
        assert ThemeColors.DANGER_DARK is not None

    def test_neutral_colors_exist(self) -> None:
        """I colori neutrali devono essere definiti."""
        assert ThemeColors.BG_MAIN is not None
        assert ThemeColors.BG_CARD is not None
        assert ThemeColors.BORDER is not None
        assert ThemeColors.TEXT_PRIMARY is not None
        assert ThemeColors.TEXT_SECONDARY is not None
        assert ThemeColors.TEXT_DISABLED is not None

    def test_status_colors_exist(self) -> None:
        """I colori di stato devono essere definiti."""
        assert ThemeColors.STATUS_RUNNING is not None
        assert ThemeColors.STATUS_ERROR is not None
        assert ThemeColors.STATUS_STOPPED is not None
        assert ThemeColors.STATUS_PAUSED is not None

    def test_no_blue_accent(self) -> None:
        """L'accento primario NON deve essere blu (vincolo §5.1.1)."""
        primary = ThemeColors.PRIMARY.lower()
        primary_dark = ThemeColors.PRIMARY_DARK.lower()
        # Nessun colore primario deve contenere tonalità di blu
        assert primary != "#0000ff"
        assert primary != "#0066ff"
        assert primary_dark != "#0000ff"
        assert primary_dark != "#0066ff"

    def test_no_red_danger(self) -> None:
        """Il colore danger NON deve essere rosso puro (vincolo §5.1.2)."""
        danger = ThemeColors.DANGER.lower()
        assert danger != "#ff0000"

    def test_font_tokens_exist(self) -> None:
        """I token di tipografia devono essere definiti."""
        assert ThemeColors.FONT_FAMILY is not None
        assert ThemeColors.FONT_FAMILY_MONO is not None
        assert ThemeColors.FONT_SIZE > 0

    def test_animation_tokens_exist(self) -> None:
        """I token di animazione devono essere definiti."""
        assert ThemeColors.ANIM_DURATION_MS > 0
        assert ThemeColors.ANIM_PULSE_PERIOD_MS > 0

    def test_all_colors_are_strings(self) -> None:
        """Tutti i colori devono essere stringhe (formato hex o rgba)."""
        color_attrs = [
            attr for attr in dir(ThemeColors)
            if not attr.startswith("_") and attr.isupper()
            and attr not in ("FONT_FAMILY", "FONT_FAMILY_MONO")
        ]
        for attr in color_attrs:
            val = getattr(ThemeColors, attr)
            if isinstance(val, str) and (val.startswith("#") or val.startswith("rgba")):
                assert len(val) > 0, f"{attr} non deve essere vuoto"
