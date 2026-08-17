"""全局底部状态栏：连接状态 + 当前任务 + 开始/停止。"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, PushButton, PrimaryPushButton, ToolButton,
    FluentIcon, CaptionLabel,
)

from app.core.task_runner import TaskRunner

TASK_NAMES = {
    "guixin_start": "一键归心",
    "sinan_start": "自动司南",
    "zhan_gong": "自动刷战功",
    "trade": "辅助交易",
    "guixin": "一键归心",
    "sinan": "自动司南",
}


class GlobalStatusBar(QWidget):
    """底部状态栏，集中展示连接/任务状态并提供全局开始/停止。

    通过 TaskRunner 信号驱动，任何 Tab 启动的任务都会在此同步显示。
    """

    def __init__(self, runner: TaskRunner, parent=None):
        super().__init__(parent)
        self.runner = runner
        self._connected = False
        self._current_task = None

        self._init_ui()
        self.runner.status.connect(self._on_connect_status)
        self.runner.task_started.connect(self._on_task_started)
        self.runner.finished.connect(self._on_task_finished)
        self.runner.sn_done.connect(lambda ok: self._on_task_finished(ok))
        self.runner.zg_done.connect(lambda ok: self._on_task_finished(ok))
        self.runner.trade_done.connect(lambda ok: self._on_task_finished(ok))

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(12)

        self.conn_dot = CaptionLabel("●")
        self.conn_dot.setStyleSheet("color: #c0c0c0; font-size: 14px;")
        self.conn_label = BodyLabel("未连接")
        self.conn_label.setStyleSheet("color: #888;")

        layout.addWidget(self.conn_dot)
        layout.addWidget(self.conn_label)

        layout.addSpacing(16)

        task_label = CaptionLabel("当前任务：")
        task_label.setStyleSheet("color: #999;")
        layout.addWidget(task_label)
        self.task_label = BodyLabel("无")
        self.task_label.setStyleSheet("color: #666;")
        layout.addWidget(self.task_label)

        self.elapsed_label = CaptionLabel("")
        self.elapsed_label.setStyleSheet("color: #999;")
        layout.addWidget(self.elapsed_label)

        layout.addStretch()

        self.start_btn = PrimaryPushButton("开始")
        self.start_btn.clicked.connect(self._on_start)
        self.start_btn.setEnabled(False)

        self.stop_btn = PushButton("停止")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)

        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)

        self._start_callback = None
        self._stop_callback = None

        # 任务持续执行计时
        self._elapsed_seconds = 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

    def set_start_callback(self, cb) -> None:
        self._start_callback = cb

    def set_stop_callback(self, cb) -> None:
        self._stop_callback = cb

    def _on_connect_status(self, ok: bool, msg: str) -> None:
        self._connected = ok
        if ok:
            self.conn_dot.setStyleSheet("color: #4caf50; font-size: 14px;")
            self.conn_label.setText("已连接")
            self.conn_label.setStyleSheet("color: #4caf50;")
            self.start_btn.setEnabled(True)
        else:
            self.conn_dot.setStyleSheet("color: #f44336; font-size: 14px;")
            self.conn_label.setText("未连接")
            self.conn_label.setStyleSheet("color: #f44336;")
            self.start_btn.setEnabled(False)

    def _on_task_started(self, task_name: str) -> None:
        self._current_task = task_name
        self.task_label.setText(TASK_NAMES.get(task_name, task_name))
        self._elapsed_seconds = 0
        self.elapsed_label.setText("已执行 00:00")
        self._timer.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def _on_task_finished(self, success: bool) -> None:
        self._current_task = None
        self.task_label.setText("无")
        self.elapsed_label.setText("")
        self._timer.stop()
        self.stop_btn.setEnabled(False)
        self.start_btn.setEnabled(self._connected)

    def _on_tick(self) -> None:
        self._elapsed_seconds += 1
        m, s = divmod(self._elapsed_seconds, 60)
        h, m = divmod(m, 60)
        if h:
            self.elapsed_label.setText(f"已执行 {h:02d}:{m:02d}:{s:02d}")
        else:
            self.elapsed_label.setText(f"已执行 {m:02d}:{s:02d}")

    def _on_start(self) -> None:
        if self._start_callback:
            self._start_callback()
            return
        from qfluentwidgets import InfoBar, InfoBarPosition
        InfoBar.warning(
            title="提示",
            content="请在对应功能页点击开始",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self,
        )

    def _on_stop(self) -> None:
        if self._stop_callback:
            self._stop_callback()
            return
        if self.runner.running:
            self.runner.stop()