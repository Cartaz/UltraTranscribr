# ui/styles/breeze_dark.py
"""Foglio di stile QSS per il tema Neumorphic Dark.

Genera l'intero stylesheet dell'applicazione come stringa QSS per
l'estetica Neumorphic Dark con colore di accento RGB(255, 102, 0) (#ff6600).
Tutti i colori, font e raggi di curvatura provengono dai token semantici
di config/theme.py.

Functions:
    build_stylesheet: Genera il foglio di stile QSS Neumorphic Dark.
"""

from __future__ import annotations

from config.theme import ThemeColors


def build_stylesheet() -> str:
    """Genera il foglio di stile QSS per il tema Neumorphic Dark.

    Returns:
        Stringa QSS completa per l'applicazione.
    """
    tc = ThemeColors
    ff = tc.FONT_FAMILY
    fs = tc.FONT_SIZE

    return f"""
    /* ═══════════════════════════════════════════════════════════════
       UltraTranscribr — Neumorphic Dark + Accent RGB(255, 102, 0)
       ═══════════════════════════════════════════════════════════════ */

    QWidget {{
        font-family: "{ff}";
        font-size: {fs}px;
        color: {tc.TEXT_PRIMARY};
    }}

    QMainWindow {{
        background-color: {tc.BG_MAIN};
    }}

    #centralContainer {{
        background-color: {tc.BG_MAIN};
        border: none;
    }}

    /* ── Card Neumorfica Estrusa ───────────────────────────────────── */

    QWidget#cardWidget {{
        background-color: {tc.BG_CARD};
        border-top: 1px solid {tc.BORDER_LIGHT};
        border-left: 1px solid {tc.BORDER_LIGHT};
        border-right: 1px solid {tc.BORDER_DARK};
        border-bottom: 1px solid {tc.BORDER_DARK};
        border-radius: 10px;
    }}

    /* ── Schede Neumorfiche (QTabWidget) ──────────────────────────── */

    QTabWidget::pane {{
        border-top: 1px solid {tc.BORDER_LIGHT};
        border-left: 1px solid {tc.BORDER_LIGHT};
        border-right: 1px solid {tc.BORDER_DARK};
        border-bottom: 1px solid {tc.BORDER_DARK};
        border-radius: 14px;
        background-color: {tc.BG_CARD};
        padding: 10px;
        top: -1px;
    }}

    QTabBar {{
        background: transparent;
        border: none;
        qproperty-drawBase: 0;
    }}

    QTabBar::tab {{
        background-color: {tc.BG_SURFACE_ALT};
        color: {tc.TEXT_DISABLED};
        border-top: 1px solid {tc.BORDER_LIGHT};
        border-left: 1px solid {tc.BORDER_LIGHT};
        border-right: 1px solid {tc.BORDER_DARK};
        border-bottom: 1px solid {tc.BORDER_DARK};
        border-radius: 8px;
        padding: 7px 30px;
        margin-right: 8px;
        min-width: 76px;
        font-size: {fs}px;
        font-weight: 500;
    }}

    QTabBar::tab:selected {{
        background-color: {tc.BG_CARD};
        color: {tc.PRIMARY};
        border: 1.5px solid {tc.PRIMARY};
        font-weight: bold;
    }}

    QTabBar::tab:hover:!selected {{
        background-color: {tc.BG_HOVER};
        color: {tc.TEXT_SECONDARY};
    }}

    /* ── Aree di testo Incavate (Inset / Recessed Surface) ───────── */

    QTextEdit#transcriptionArea,
    QTextEdit#fileTranscriptionArea {{
        background-color: {tc.BG_SURFACE};
        color: {tc.TEXT_PRIMARY};
        border-top: 1px solid {tc.BORDER_DARK};
        border-left: 1px solid {tc.BORDER_DARK};
        border-right: 1px solid {tc.BORDER_LIGHT};
        border-bottom: 1px solid {tc.BORDER_LIGHT};
        border-radius: 10px;
        padding: 14px;
        font-family: "{ff}";
        font-size: {fs}px;
        selection-background-color: {tc.BG_SELECTION};
        selection-color: {tc.TEXT_ON_SELECTION};
    }}

    QTextEdit#transcriptionArea:focus,
    QTextEdit#fileTranscriptionArea:focus {{
        border: 1px solid {tc.BORDER_FOCUS};
    }}

    /* ── Barra di stato Incavata ──────────────────────────────────── */

    #statusBar {{
        background-color: transparent;
        border: none;
        padding: 2px 4px;
        min-height: 24px;
    }}

    #statusBar QLabel {{
        color: {tc.TEXT_SECONDARY};
        font-size: {fs - 1}px;
        padding: 0;
        background: transparent;
    }}

    /* ── Pulsanti Neumorfici ──────────────────────────────────────── */

    QPushButton {{
        background-color: {tc.BG_CARD};
        color: {tc.TEXT_PRIMARY};
        border-top: 1px solid {tc.BORDER_LIGHT};
        border-left: 1px solid {tc.BORDER_LIGHT};
        border-right: 1px solid {tc.BORDER_DARK};
        border-bottom: 1px solid {tc.BORDER_DARK};
        border-radius: 8px;
        padding: 6px 16px;
        min-height: 26px;
        font-weight: 600;
    }}

    QPushButton:hover {{
        background-color: {tc.BG_HOVER};
        color: {tc.TEXT_PRIMARY};
    }}

    QPushButton:pressed {{
        background-color: {tc.BG_ACTIVE};
        border-top: 1px solid {tc.BORDER_DARK};
        border-left: 1px solid {tc.BORDER_DARK};
        border-right: 1px solid {tc.BORDER_LIGHT};
        border-bottom: 1px solid {tc.BORDER_LIGHT};
        color: {tc.PRIMARY};
        padding-top: 7px;
        padding-left: 17px;
    }}

    QPushButton:disabled {{
        background-color: {tc.BG_SURFACE};
        color: {tc.TEXT_DISABLED};
        border: 1px solid {tc.BORDER};
    }}

    /* ── ComboBox Neumorfico (Incavato con indicatore arancione) ──── */

    QComboBox {{
        background-color: {tc.BG_SURFACE};
        color: {tc.TEXT_PRIMARY};
        border-top: 1px solid {tc.BORDER_DARK};
        border-left: 1px solid {tc.BORDER_DARK};
        border-right: 1px solid {tc.BORDER_LIGHT};
        border-bottom: 1px solid {tc.BORDER_LIGHT};
        border-radius: 7px;
        padding: 6px 12px;
        min-height: 22px;
    }}

    QComboBox:hover {{
        border-color: {tc.BORDER_LIGHT};
    }}

    QComboBox:focus {{
        border: 1px solid {tc.BORDER_FOCUS};
    }}

    QComboBox::drop-down {{
        border: none;
        padding-right: 8px;
        subcontrol-origin: padding;
        subcontrol-position: top right;
    }}

    QComboBox::down-arrow {{
        image: none;
        width: 7px;
        height: 7px;
        background-color: {tc.PRIMARY};
        border-radius: 1.5px;
        margin-right: 8px;
    }}

    QComboBox QAbstractItemView {{
        background-color: {tc.BG_CARD};
        color: {tc.TEXT_PRIMARY};
        border: 1px solid {tc.BORDER};
        border-radius: 6px;
        selection-background-color: {tc.BG_SELECTION};
        selection-color: {tc.TEXT_ON_SELECTION};
        outline: none;
        padding: 4px;
    }}

    /* ── CheckBox Neumorfico ──────────────────────────────────────── */

    QCheckBox {{
        color: {tc.TEXT_PRIMARY};
        spacing: 8px;
        min-height: 22px;
    }}

    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-top: 1px solid {tc.BORDER_DARK};
        border-left: 1px solid {tc.BORDER_DARK};
        border-right: 1px solid {tc.BORDER_LIGHT};
        border-bottom: 1px solid {tc.BORDER_LIGHT};
        border-radius: 4px;
        background-color: {tc.BG_SURFACE};
    }}

    QCheckBox::indicator:checked {{
        background-color: {tc.PRIMARY};
        border: 1px solid {tc.PRIMARY_LIGHT};
    }}

    QCheckBox::indicator:hover {{
        border-color: {tc.PRIMARY};
    }}

    /* ── Titoli e Testi ───────────────────────────────────────────── */

    QLabel {{
        background: transparent;
        color: {tc.TEXT_SECONDARY};
    }}

    QLabel#titleLabel {{
        font-size: {fs + 7}px;
        font-weight: bold;
        color: {tc.PRIMARY};
        padding: 2px 0 0 0;
        letter-spacing: 0.3px;
    }}

    QLabel#subtitleLabel {{
        font-size: {fs - 1}px;
        color: {tc.TEXT_DISABLED};
        padding: 0 0 6px 0;
    }}

    /* ── ProgressBar Neumorfica Incavata ─────────────────────────── */

    QProgressBar#fileProgressBar,
    QProgressBar#bufferBar {{
        background-color: {tc.BG_SURFACE};
        border-top: 1px solid {tc.BORDER_DARK};
        border-left: 1px solid {tc.BORDER_DARK};
        border-right: 1px solid {tc.BORDER_LIGHT};
        border-bottom: 1px solid {tc.BORDER_LIGHT};
        border-radius: 5px;
        min-height: 10px;
        max-height: 10px;
        text-align: center;
    }}

    QProgressBar#fileProgressBar::chunk,
    QProgressBar#bufferBar::chunk {{
        background-color: {tc.PRIMARY};
        border-radius: 4px;
    }}

    /* ── ScrollBar Neumorfica ─────────────────────────────────────── */

    QScrollBar:vertical {{
        background: {tc.SCROLLBAR_BG};
        width: 10px;
        border: none;
        border-radius: 5px;
    }}

    QScrollBar::handle:vertical {{
        background: {tc.SCROLLBAR_HANDLE};
        border-radius: 5px;
        min-height: 30px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {tc.SCROLLBAR_HANDLE_HOVER};
    }}

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0;
    }}

    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: none;
    }}

    /* ── Menu e Tooltip ───────────────────────────────────────────── */

    QMenu {{
        background-color: {tc.BG_CARD};
        border-top: 1px solid {tc.BORDER_LIGHT};
        border-left: 1px solid {tc.BORDER_LIGHT};
        border-right: 1px solid {tc.BORDER_DARK};
        border-bottom: 1px solid {tc.BORDER_DARK};
        border-radius: 8px;
        padding: 6px;
    }}

    QMenu::item {{
        padding: 6px 24px;
        border-radius: 5px;
    }}

    QMenu::item:selected {{
        background-color: {tc.BG_SELECTION};
        color: {tc.TEXT_ON_SELECTION};
    }}

    QMenu::separator {{
        height: 1px;
        background-color: {tc.BORDER};
        margin: 4px 8px;
    }}

    QToolTip {{
        background-color: {tc.BG_TOOLTIP};
        color: {tc.TEXT_PRIMARY};
        border: 1px solid {tc.BORDER_LIGHT};
        border-radius: 6px;
        padding: 5px 10px;
    }}
    """
