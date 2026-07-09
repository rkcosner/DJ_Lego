"""Application entry point: create the Qt app, apply the theme, show the booth."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow
from .ui import theme


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("DJ Lego")
    app.setStyleSheet(theme.QSS)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
