# ui/styles/breeze_dark.py
"""QSS complementare al renderer QPainter Dark Neumorphism."""

from __future__ import annotations

from config.theme import ThemeColors


def build_stylesheet() -> str:
    tc = ThemeColors
    ff = tc.FONT_FAMILY
    fs = tc.FONT_SIZE

    return f"""
    QWidget {{
        font-family: "{ff}";
        font-size: {fs}px;
        color: {tc.TEXT_PRIMARY};
    }}

    QMainWindow,
    QDialog,
    QMessageBox {{
        background-color: {tc.BG_MAIN};
        color: {tc.TEXT_PRIMARY};
    }}

    #centralContainer {{
        background-color: {tc.BG_MAIN};
        border: none;
    }}

    /* Le Card vere sono dipinte da Card.paintEvent / QPainter. */
    QWidget#cardWidget {{
        background: transparent;
        border: none;
    }}

    QTabWidget::pane {{
        background-color: {tc.BG_CARD};
        border-top: 1px solid {tc.BORDER_LIGHT};
        border-left: 1px solid {tc.BORDER_LIGHT};
        border-right: 1px solid {tc.BORDER_DARK};
        border-bottom: 1px solid {tc.BORDER_DARK};
        border-radius: 14px;
        padding: 10px;
        top: -1px;
    }}

    QTabBar {{
        background: transparent;
        border: none;
        qproperty-drawBase: 0;
    }}

    QTabBar::tab {{
        background-color: {tc.BG_CARD};
        color: {tc.TEXT_DISABLED};
        border-top: 1px solid {tc.BORDER_LIGHT};
        border-left: 1px solid {tc.BORDER_LIGHT};
        border-right: 1px solid {tc.BORDER_DARK};
        border-bottom: 1px solid {tc.BORDER_DARK};
        border-radius: 9px;
        padding: 7px 30px;
        margin-right: 8px;
        min-width: 76px;
        font-weight: 500;
    }}

    QTabBar::tab:selected {{
        background-color: {tc.BG_ACTIVE};
        color: {tc.PRIMARY};
        border: 2px solid {tc.PRIMARY};
        font-weight: 700;
    }}

    QTabBar::tab:hover:!selected {{
        background-color: {tc.BG_HOVER};
        color: {tc.TEXT_PRIMARY};
        border-top-color: {tc.SHADOW_LIGHT};
        border-left-color: {tc.SHADOW_LIGHT};
    }}

    QTextEdit#transcriptionArea,
    QTextEdit#fileTranscriptionArea {{
        background-color: {tc.BG_SURFACE};
        color: {tc.TEXT_PRIMARY};
        border-top: 2px solid {tc.BORDER_DARK};
        border-left: 2px solid {tc.BORDER_DARK};
        border-right: 1px solid {tc.BORDER_LIGHT};
        border-bottom: 1px solid {tc.BORDER_LIGHT};
        border-radius: 11px;
        padding: 14px;
        selection-background-color: {tc.BG_SELECTION};
        selection-color: {tc.TEXT_ON_SELECTION};
    }}

    QTextEdit#transcriptionArea:focus,
    QTextEdit#fileTranscriptionArea:focus {{
        border: 1px solid {tc.BORDER_FOCUS};
    }}

    #statusBar {{
        background-color: {tc.BG_CARD};
        border-top: 1px solid {tc.BORDER_LIGHT};
        border-left: 1px solid {tc.BORDER_LIGHT};
        border-right: 1px solid {tc.BORDER_DARK};
        border-bottom: 1px solid {tc.BORDER_DARK};
        border-radius: 12px;
        padding: 2px 4px;
        min-height: 24px;
    }}

    #statusBar QLabel {{
        color: {tc.TEXT_SECONDARY};
        font-size: {fs - 1}px;
        padding: 0;
        background: transparent;
        border: none;
    }}

    /* Fallback per QPushButton standard; ActionButton usa QPainter. */
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
    }}

    QPushButton:pressed {{
        background-color: {tc.BG_ACTIVE};
        border-top: 1px solid {tc.BORDER_DARK};
        border-left: 1px solid {tc.BORDER_DARK};
        border-right: 1px solid {tc.BORDER_LIGHT};
        border-bottom: 1px solid {tc.BORDER_LIGHT};
    }}

    QPushButton:focus {{
        border: 1px solid {tc.BORDER_FOCUS};
    }}

    QPushButton:disabled {{
        background-color: {tc.BG_ACTIVE};
        color: {tc.TEXT_DISABLED};
        border: 1px solid {tc.BORDER};
    }}

    /*
      QComboBox custom: il volto del controllo viene dipinto da QPainter.
      QSS resta responsabile di metriche e popup.
    */
    QComboBox {{
        background: transparent;
        color: {tc.TEXT_PRIMARY};
        border: none;
        border-radius: 8px;
        padding: 6px 12px;
        min-height: 22px;
    }}

    QComboBox::drop-down {{
        width: 24px;
        border: none;
        background: transparent;
    }}

    QComboBox::down-arrow {{
        image: none;
        width: 0;
        height: 0;
    }}

    QComboBox QAbstractItemView {{
        background-color: {tc.BG_CARD};
        color: {tc.TEXT_PRIMARY};
        border: 1px solid {tc.BORDER_LIGHT};
        selection-background-color: {tc.BG_SELECTION};
        selection-color: {tc.TEXT_ON_SELECTION};
        outline: none;
        padding: 4px;
    }}

    QCheckBox {{
        color: {tc.TEXT_PRIMARY};
        spacing: 8px;
        min-height: 22px;
    }}

    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        background-color: {tc.BG_SURFACE};
        border-top: 1px solid {tc.BORDER_DARK};
        border-left: 1px solid {tc.BORDER_DARK};
        border-right: 1px solid {tc.BORDER_LIGHT};
        border-bottom: 1px solid {tc.BORDER_LIGHT};
        border-radius: 5px;
    }}

    QCheckBox::indicator:checked {{
        background-color: {tc.PRIMARY};
        border: 1px solid {tc.PRIMARY_LIGHT};
    }}

    QCheckBox:focus {{
        color: {tc.PRIMARY};
    }}

    QLabel {{
        background: transparent;
        color: {tc.TEXT_SECONDARY};
    }}

    QLabel#titleLabel {{
        font-size: {fs + 7}px;
        font-weight: 700;
        color: {tc.PRIMARY};
        padding: 2px 0 0 0;
        letter-spacing: 0.3px;
    }}

    QLabel#subtitleLabel {{
        font-size: {fs - 1}px;
        color: {tc.TEXT_DISABLED};
        padding: 0 0 6px 0;
    }}

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

    QScrollBar:horizontal {{
        background: {tc.SCROLLBAR_BG};
        height: 10px;
        border: none;
        border-radius: 5px;
    }}

    QScrollBar::handle:horizontal {{
        background: {tc.SCROLLBAR_HANDLE};
        border-radius: 5px;
        min-width: 30px;
    }}

    QScrollBar::handle:horizontal:hover {{
        background: {tc.SCROLLBAR_HANDLE_HOVER};
    }}

    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {{
        background: none;
    }}

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

    QMenu::item:disabled {{
        color: {tc.TEXT_DISABLED};
    }}

    QToolTip {{
        background-color: {tc.BG_TOOLTIP};
        color: {tc.TEXT_PRIMARY};
        border: 1px solid {tc.BORDER_LIGHT};
        border-radius: 6px;
        padding: 5px 10px;
    }}
    """
