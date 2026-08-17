"""右侧共享日志面板。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QTextEdit
from qfluentwidgets import BodyLabel, CardWidget, PushButton, FluentIcon


class LogPanel(CardWidget):
    """三栏式右侧的全局共享日志区：所有任务的输出统一显示在这里。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # 顶部：标题 + 清空按钮
        header = QHBoxLayout()
        header.setSpacing(8)
        title = BodyLabel("运行日志")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()
        clear_btn = PushButton(FluentIcon.DELETE, "清空")
        clear_btn.setFixedWidth(80)
        clear_btn.clicked.connect(self.clear)
        header.addWidget(clear_btn)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet(
            "QTextEdit { background: #fafafa; border: 1px solid #e0e0e0; "
            "border-radius: 8px; padding: 8px; "
            "font-family: Consolas, monospace; font-size: 12px; }"
        )

        layout.addLayout(header)
        layout.addWidget(self.log_view, 1)

    def append(self, msg: str, max_lines: int = 1000) -> None:
        self.log_view.append(str(msg))
        lines = self.log_view.document().blockCount()
        if lines > max_lines:
            cursor = self.log_view.textCursor()
            cursor.setPosition(0)
            cursor.movePosition(
                cursor.MoveOperation.Down,
                cursor.MoveMode.KeepAnchor,
                lines - max_lines,
            )
            cursor.removeSelectedText()
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum()
        )

    def clear(self) -> None:
        self.log_view.clear()