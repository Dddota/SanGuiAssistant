"""三国天下归心 - 一键长草小助手 主入口。"""
from __future__ import annotations

import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import FluentTranslator

from app.core.config import assets_root
from app.view.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("三归小助手")

    icon_path = assets_root() / "image" / "app_icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    translator = FluentTranslator()
    app.installTranslator(translator)

    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
