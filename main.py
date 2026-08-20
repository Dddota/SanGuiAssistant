"""三国天下归心 - 一键长草小助手 主入口。"""
from __future__ import annotations

import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox
from qfluentwidgets import FluentTranslator

from app import __app_name__
from app.core.config import assets_root
from app.utils.logger import setup_logger
from app.view.agreement import confirm_agreement
from app.view.main_window import MainWindow


def main() -> None:
    setup_logger()  # 开启应用日志落盘（logs/app.log），便于崩溃/运行时排查
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)

    icon_path = assets_root() / "image" / "app_icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # 首次启动需同意用户协议；拒绝即退出
    if not confirm_agreement():
        QMessageBox.warning(
            None, "未同意用户协议",
            "您未同意《三归小助手》用户协议，程序即将退出。",
        )
        sys.exit(1)

    translator = FluentTranslator()
    app.installTranslator(translator)

    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
