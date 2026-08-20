# config/theme.py
"""Token di colore semantici e helper per il tema Neumorphic Dark.

Questo modulo definisce tutti i colori dell'applicazione come costanti
semantiche e fornisce la configurazione per il rendering neumorfico
(superfici estruse, incavi, luci soffuse e ombre scure) con colore
accento RGB(255, 102, 0) (#ff6600).

Classes:
    ThemeColors: Token di colore centralizzati per Neumorphic Dark.
    NeumorphicTheme: Configurazione e helper per il rendering neumorfico Qt.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from PySide6.QtGui import QColor
except ImportError:
    class QColor:  # type: ignore[no-redef]
        """Fallback mock QColor when PySide6 is not installed."""
        def __init__(self, *args, **kwargs) -> None:
            self._args = args
        def setAlpha(self, a: int) -> None:
            pass
        def setAlphaF(self, a: float) -> None:
            pass


class ThemeColors:
    """Token di colore semantici per Neumorphic Dark.

    Nessun componente UI deve usare valori hex al di fuori di questa classe.
    I token sono organizzati per ruolo semantico con colore di accento
    RGB(255, 102, 0) (#ff6600).
    """

    # ── Accento primario — Arancione Neumorphic (RGB: 255, 102, 0) ──
    PRIMARY: str = "#ff6600"
    PRIMARY_LIGHT: str = "#ff8533"
    PRIMARY_DARK: str = "#cc5200"
    PRIMARY_DEEP: str = "#803300"
    PRIMARY_GLOW: str = "rgba(255, 102, 0, 0.28)"

    # ── Azioni distruttive / Avviso — Rosso Corallo Neumorfico ───────
    DANGER: str = "#e63946"
    DANGER_LIGHT: str = "#ff4d5a"
    DANGER_DARK: str = "#991b24"
    DANGER_GLOW: str = "rgba(230, 57, 70, 0.25)"

    # ── Colori neutrali e superfici neumorfiche ─────────────────────
    BG_MAIN: str = "#181a1d"          # Sfondo finestra principale
    BG_CARD: str = "#22262c"          # Superficie estrusa di base (materiale neumorfico)
    BG_SURFACE: str = "#1a1d21"       # Superficie incavata / campi di input
    BG_SURFACE_ALT: str = "#272c33"   # Superficie leggermente elevata per controlli
    BG_HOVER: str = "#2d333b"         # Stato hover rialzato
    BG_ACTIVE: str = "#191b1e"        # Stato premuto / depresso

    # ── Luci e ombre neumorfiche ─────────────────────────────────────
    SHADOW_LIGHT: str = "#2f353d"     # Luce morbida alto/sinistra
    SHADOW_DARK: str = "#101214"      # Ombra profonda basso/destra
    BORDER: str = "#2c3138"           # Bordo di transizione morbido
    BORDER_LIGHT: str = "#363c45"     # Bordo superiore chiaro
    BORDER_DARK: str = "#141618"      # Bordo inferiore scuro
    BORDER_FOCUS: str = "#ff6600"     # Bordo di focus accento (RGB 255,102,0)

    # ── Tipografia e contrasto ───────────────────────────────────────
    TEXT_PRIMARY: str = "#f0f2f5"
    TEXT_SECONDARY: str = "#9ba3af"
    TEXT_DISABLED: str = "#555d68"
    TEXT_ON_ACCENT: str = "#ffffff"
    TEXT_ON_SELECTION: str = "#ffffff"

    # ── Elementi interattivi ─────────────────────────────────────────
    BG_TOOLTIP: str = "#22262c"
    BG_SELECTION: str = "#803300"
    BG_BADGE: str = "rgba(255, 255, 255, 0.06)"

    # ── Icona Tray ───────────────────────────────────────────────────
    ICON_BORDER: str = "rgba(0, 0, 0, 80)"
    ICON_TEXT_SHADOW: str = "rgba(0, 0, 0, 180)"

    # ── Indicatori di stato ──────────────────────────────────────────
    STATUS_RUNNING: str = "#2ecc71"
    STATUS_ERROR: str = "#e63946"
    STATUS_STOPPED: str = "#555d68"
    STATUS_PAUSED: str = "#ff6600"
    STATUS_BUFFERING: str = "#f39c12"
    STATUS_LOADING: str = "#ff6600"

    # ── Scrollbar ────────────────────────────────────────────────────
    SCROLLBAR_BG: str = "#1a1d21"
    SCROLLBAR_HANDLE: str = "#363c45"
    SCROLLBAR_HANDLE_HOVER: str = "#ff6600"

    # ── Tipografia ───────────────────────────────────────────────────
    FONT_FAMILY: str = "Noto Sans"
    FONT_FAMILY_MONO: str = "Sarasa Mono SC"
    FONT_SIZE: int = 13

    # ── Animazioni ───────────────────────────────────────────────────
    ANIM_DURATION_MS: int = 200
    ANIM_PULSE_PERIOD_MS: int = 1500


@dataclass(frozen=True)
class NeumorphicTheme:
    """Configurazione grafica e geometrica per il rendering neumorfico."""

    bg: str = ThemeColors.BG_CARD
    bg_dark: str = ThemeColors.BG_MAIN
    bg_surface: str = ThemeColors.BG_SURFACE
    accent: str = ThemeColors.PRIMARY
    accent_dark: str = ThemeColors.PRIMARY_DARK
    danger: str = ThemeColors.DANGER
    text_primary: str = ThemeColors.TEXT_PRIMARY
    text_secondary: str = ThemeColors.TEXT_SECONDARY
    text_disabled: str = ThemeColors.TEXT_DISABLED

    shadow_light: str = ThemeColors.SHADOW_LIGHT
    shadow_dark: str = ThemeColors.SHADOW_DARK

    raised_light_alpha: int = 160
    raised_dark_alpha: int = 180
    inset_light_alpha: int = 90
    inset_dark_alpha: int = 170

    shadow_offset: float = 6.0
    focus_width: float = 1.8
    focus_inset: float = 2.0
    progress_inset: int = 4
    disabled_opacity: float = 0.45

    radius_sm: int = 6
    radius_md: int = 8
    radius_lg: int = 12

    control_height: int = 34
    tab_height: int = 38
    page_shadow_margin: int = 8
    card_shadow_margin: int = 6

    font_family: str = ThemeColors.FONT_FAMILY
    font_size: int = ThemeColors.FONT_SIZE

    @staticmethod
    def qcolor(color_spec: str) -> QColor:
        """Converte una stringa hex o rgba in QColor."""
        if color_spec.startswith("rgba"):
            parts = color_spec.strip("rgba() ").split(",")
            if len(parts) == 4:
                r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                a = float(parts[3])
                return QColor(r, g, b, int(a * 255 if a <= 1.0 else a))
        return QColor(color_spec)


theme = NeumorphicTheme()
