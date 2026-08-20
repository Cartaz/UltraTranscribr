# config/theme.py
"""Token centralizzati per il tema Dark Neumorphism di UltraTranscribr."""

from __future__ import annotations

from dataclasses import dataclass

try:
    from PySide6.QtGui import QColor
except ImportError:
    class QColor:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs) -> None:
            self._args = args
        def setAlpha(self, a: int) -> None:
            pass
        def setAlphaF(self, a: float) -> None:
            pass


class ThemeColors:
    """Palette Dark Neumorphism con accento obbligatorio #FF6600."""

    # Accent
    PRIMARY: str = "#FF6600"
    PRIMARY_LIGHT: str = "#FF8533"
    PRIMARY_DARK: str = "#CC5200"
    PRIMARY_DEEP: str = "#803300"
    PRIMARY_GLOW: str = "rgba(255, 102, 0, 0.24)"

    # Danger
    DANGER: str = "#E63946"
    DANGER_LIGHT: str = "#FF4D5A"
    DANGER_DARK: str = "#991B24"
    DANGER_GLOW: str = "rgba(230, 57, 70, 0.25)"

    # Base material — richiesto: RGB(20,20,20)
    BG_MAIN: str = "#141414"
    BG_CARD: str = "#202225"
    BG_SURFACE: str = "#171819"
    BG_SURFACE_ALT: str = "#24272B"
    BG_HOVER: str = "#272A2F"
    BG_ACTIVE: str = "#151617"

    # Neumorphic light/shadow pair
    SHADOW_LIGHT: str = "#34383E"
    SHADOW_DARK: str = "#070809"
    BORDER: str = "#272A2E"
    BORDER_LIGHT: str = "#383C42"
    BORDER_DARK: str = "#090A0B"
    BORDER_FOCUS: str = "#FF6600"

    # Text
    TEXT_PRIMARY: str = "#ECEFF1"
    TEXT_SECONDARY: str = "#A7ADB4"
    TEXT_DISABLED: str = "#6F757C"
    TEXT_ON_ACCENT: str = "#111111"
    TEXT_ON_SELECTION: str = "#ECEFF1"

    # Interactive
    BG_TOOLTIP: str = "#202225"
    BG_SELECTION: str = "#5A2A0A"
    BG_BADGE: str = "rgba(255, 255, 255, 0.05)"

    # Tray
    ICON_BORDER: str = "rgba(0, 0, 0, 80)"
    ICON_TEXT_SHADOW: str = "rgba(0, 0, 0, 180)"

    # Status
    STATUS_RUNNING: str = "#2ECC71"
    STATUS_ERROR: str = "#E63946"
    STATUS_STOPPED: str = "#747A82"
    STATUS_PAUSED: str = "#FF6600"
    STATUS_BUFFERING: str = "#F39C12"
    STATUS_LOADING: str = "#FF6600"

    # Scrollbar
    SCROLLBAR_BG: str = "#171819"
    SCROLLBAR_HANDLE: str = "#34383E"
    SCROLLBAR_HANDLE_HOVER: str = "#FF6600"

    # Typography
    FONT_FAMILY: str = "Noto Sans"
    FONT_FAMILY_MONO: str = "Sarasa Mono SC"
    FONT_SIZE: int = 13

    # Motion
    ANIM_DURATION_MS: int = 160
    ANIM_PULSE_PERIOD_MS: int = 1500


@dataclass(frozen=True)
class NeumorphicTheme:
    """Rendering tokens. Non ridefinisce il layout dell'app."""

    bg: str = ThemeColors.BG_CARD
    bg_dark: str = ThemeColors.BG_MAIN
    bg_surface: str = ThemeColors.BG_SURFACE
    bg_surface_alt: str = ThemeColors.BG_SURFACE_ALT
    accent: str = ThemeColors.PRIMARY
    accent_dark: str = ThemeColors.PRIMARY_DARK
    danger: str = ThemeColors.DANGER
    text_primary: str = ThemeColors.TEXT_PRIMARY
    text_secondary: str = ThemeColors.TEXT_SECONDARY
    text_disabled: str = ThemeColors.TEXT_DISABLED

    shadow_light: str = ThemeColors.SHADOW_LIGHT
    shadow_dark: str = ThemeColors.SHADOW_DARK

    # Più marcati della v1 per avvicinarsi al mockup approvato.
    raised_light_alpha: int = 178
    raised_dark_alpha: int = 225
    inset_light_alpha: int = 112
    inset_dark_alpha: int = 218

    shadow_offset: float = 7.0
    focus_width: float = 1.8
    focus_inset: float = 2.0
    progress_inset: int = 4
    disabled_opacity: float = 0.50

    radius_sm: int = 8
    radius_md: int = 10
    radius_lg: int = 14

    # Compatibilità con widget esistenti; non vengono imposte nuove geometrie.
    control_height: int = 34
    tab_height: int = 38
    page_shadow_margin: int = 8
    card_shadow_margin: int = 8

    font_family: str = ThemeColors.FONT_FAMILY
    font_size: int = ThemeColors.FONT_SIZE

    @staticmethod
    def qcolor(color_spec: str) -> QColor:
        if color_spec.startswith("rgba"):
            parts = color_spec.strip("rgba() ").split(",")
            if len(parts) == 4:
                r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                a = float(parts[3])
                return QColor(r, g, b, int(a * 255 if a <= 1.0 else a))
        return QColor(color_spec)


theme = NeumorphicTheme()
