"""Shared dark "mixer" palette, used by both the Qt stylesheet and the plots."""

# Core surfaces
BG = "#14161c"       # window background
PANEL = "#1c2029"    # raised panels / rack
PANEL_HI = "#252b37" # hover / selected
LINE = "#333a48"     # borders / gridlines
TEXT = "#e6e9ef"     # primary text
TEXT_DIM = "#93a0b4" # secondary text

# Accents (also the chart series colors)
ACCENT = "#4fd1c5"   # teal — primary / "output"
ACCENT2 = "#f6ad55"  # amber — phase / secondary
INPUT = "#7c8598"    # muted grey — "input" signal
MAG = "#4fd1c5"      # Bode magnitude
PHASE = "#f6ad55"    # Bode phase
DANGER = "#fc8181"   # instability / warnings

QSS = f"""
* {{
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    color: {TEXT};
}}
QMainWindow, QWidget {{ background: {BG}; }}
QLabel#h1 {{ font-size: 15px; font-weight: 600; color: {TEXT}; }}
QLabel#dim {{ color: {TEXT_DIM}; }}
QLabel#tf {{ font-family: "Consolas", "Menlo", monospace; font-size: 15px; }}
QFrame#panel {{
    background: {PANEL};
    border: 1px solid {LINE};
    border-radius: 10px;
}}
QPushButton {{
    background: {PANEL};
    border: 1px solid {LINE};
    border-radius: 8px;
    padding: 7px 12px;
}}
QPushButton:hover {{ background: {PANEL_HI}; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {PANEL_HI}; }}
QPushButton#accent {{
    background: {ACCENT}; color: #0b1013; font-weight: 600; border: none;
}}
QPushButton#accent:hover {{ background: #6ee0d5; }}
QPushButton#bypass:checked {{
    background: {ACCENT2}; color: #0b1013; font-weight: 600; border: none;
}}
QPushButton#bypass:checked:hover {{ background: #f8c078; }}
QListWidget {{
    background: {PANEL};
    border: 1px solid {LINE};
    border-radius: 10px;
    padding: 6px;
    outline: none;
}}
QListWidget::item {{
    background: {PANEL_HI};
    border: 1px solid {LINE};
    border-radius: 8px;
    padding: 10px 12px;
    margin: 4px 2px;
}}
QListWidget::item:selected {{
    border: 2px solid {ACCENT};
    background: {PANEL_HI};
    color: {TEXT};
}}
QSlider::groove:horizontal {{
    height: 4px; background: {LINE}; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT}; width: 16px; height: 16px;
    margin: -7px 0; border-radius: 8px;
}}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid {LINE}; background: {PANEL};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QToolTip {{
    background: {PANEL}; color: {TEXT}; border: 1px solid {ACCENT};
    padding: 6px; border-radius: 6px;
}}
"""
