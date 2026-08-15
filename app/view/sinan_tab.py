"""自动司南 Tab。"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QTextEdit,
    QProgressBar,
)
from qfluentwidgets import (
    PrimaryPushButton, PushButton, CardWidget, BodyLabel,
    TitleLabel, SubtitleLabel, InfoBar, InfoBarPosition,
)

from app.core.task_runner import TaskRunner

logger = logging.getLogger("sangui.gui")


class SinanTab(QWidget):
    def __init__(self, runner: TaskRunner, parent=None):
        super().__init__(parent)
        self.setObjectName("sinanTab")
        self.parent_window = parent
        self.runner = runner
        self._connected = False

        self._init_ui()
        self.runner.status.connect(self._on_connect_status)
        self.runner.sn_progress.connect(self._on_progress)
        self.runner.sn_done.connect(self._on_task_finished)

    def _on_connect_status(self, ok: bool, msg: str) -> None:
        if ok:
            self._connected = True
            self.status_label.setText("状态：已连接模拟器")
            self.start_btn.setEnabled(True)
            self._append_log("已连接 MuMu Player 12")
            self._append_log("资源加载完成")
        else:
            self.status_label.setText(f"状态：连接失败 - {msg}")
            self._append_log(f"连接失败: {msg}")

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        title = TitleLabel("自动司南")
        layout.addWidget(title)

        subtitle = SubtitleLabel("自动使用所有可用的司南")
        subtitle.setStyleSheet("color: #666;")
        layout.addWidget(subtitle)

        status_card = CardWidget()
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(20, 15, 20, 15)
        status_layout.setSpacing(10)

        self.status_label = BodyLabel("状态：未连接")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.progress)
        layout.addWidget(status_card)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.start_btn = PrimaryPushButton("开始司南")
        self.start_btn.clicked.connect(self._on_start)
        self.start_btn.setEnabled(False)

        self.stop_btn = PushButton("停止")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)

        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        log_label = BodyLabel("运行日志")
        layout.addWidget(log_label)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(300)
        self.log_view.setStyleSheet(
            "QTextEdit { background: #f7f7f7; border: 1px solid #e0e0e0; "
            "border-radius: 8px; padding: 8px; font-family: Consolas, monospace; }"
        )
        layout.addWidget(self.log_view)

        layout.addStretch()

    def _append_log(self, msg: str, max_lines: int = 500) -> None:
        self.log_view.append(msg)
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

    def _on_start(self) -> None:
        if not self._connected:
            InfoBar.error(
                title="错误",
                content="未连接模拟器",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
            return

        if self.runner.running:
            return

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setValue(0)
        self.status_label.setText("状态：司南使用中...")
        self._append_log("=" * 40)
        self._append_log("开始执行司南任务")

        self.runner.start_sinan()

    def _on_stop(self) -> None:
        if self.runner.running:
            self.runner.stop()
            self._append_log("已请求停止")

    def _on_progress(self, msg: str) -> None:
        self._append_log(msg)

    def _on_task_finished(self, success: bool) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setValue(100 if success else 0)

        if success:
            self.status_label.setText("状态：司南完成")
            self._append_log("司南任务完成")
            InfoBar.success(
                title="完成",
                content="司南使用完毕",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
        else:
            self.status_label.setText("状态：任务失败/已停止")
            self._append_log("任务失败或已停止")
            InfoBar.warning(
                title="警告",
                content="任务未完成或已停止",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
