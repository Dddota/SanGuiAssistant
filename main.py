"""三国天下归心 - 一键长草小助手 主入口。"""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication
from qfluentwidgets import FluentTranslator

from app.view.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("三归小助手")

    translator = FluentTranslator()
    app.installTranslator(translator)

    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
