"""全局底部状态栏：单行横排，开始/停止按钮 + 连接状态/任务/耗时。

布局（与上方 Dashboard 三栏同比例对齐）：
    中区（对应中栏，占 3 份）          右区（对应右栏=运行日志，占 2 份）
    ┌───────────────────────────────┐  ┌──────────────────────────────┐
    │ [ 开始/停止 ]                  │  │ ●已连接 · 当前任务: xxx  ... │
    └───────────────────────────────┘  └──────────────────────────────┘
右区内信息左对齐，保证「已连接」组起始位置与运行日志栏左缘齐平。
完成后齿轮组已移至 Dashboard 左栏底部。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, PrimaryPushButton,
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
    """底部状态栏，单行横排：左侧开始/停止按钮，右侧连接状态 + 当前任务 + 已执行时间。

    布局比例与 Dashboard 三栏对齐：左240px占位 + 中栏(3份) + 右栏(2份)。
    右区信息左对齐 → 与日志栏左缘齐平。

    通过 TaskRunner 信号驱动，任何 Tab 启动的任务都会在此同步显示。
    """

    def __init__(self, runner: TaskRunner, parent=None):
        super().__init__(parent)
        self.runner = runner
        self._connected = False
        self._running = False     # 是否处于运行中（决定按钮是"开始"还是"停止"）
        self._current_task = None

        self._init_ui()
        self.runner.status.connect(self._on_connect_status)
        self.runner.task_started.connect(self._on_task_started)
        self.runner.finished.connect(self._on_task_finished)
        self.runner.sn_done.connect(lambda ok: self._on_task_finished(ok))
        self.runner.zg_done.connect(lambda ok: self._on_task_finished(ok))
        self.runner.trade_done.connect(lambda ok: self._on_task_finished(ok))

    def _init_ui(self) -> None:
        # 状态栏整体布局：与 Dashboard 三栏结构镜像对齐
        #   [左占位 240px] [间距] [中区(3份)] [间距] [右区(2份)=对齐日志栏]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(16)  # 与 Dashboard 间距一致

        # 左侧占位：宽 240px，对应 Dashboard 左栏（任务清单卡片 + 完成后）的位置
        left_placeholder = QWidget()
        left_placeholder.setFixedWidth(240)
        layout.addWidget(left_placeholder, 0)

        # ---- 中间区域（对应 Dashboard 中栏，占 3 份 stretch）----
        # 放置：开始/停止切换按钮
        mid_zone = QHBoxLayout()
        mid_zone.setSpacing(12)
        mid_zone.setContentsMargins(0, 0, 0, 0)

        self.toggle_btn = PrimaryPushButton("开始")
        self.toggle_btn.setEnabled(False)
        self.toggle_btn.setFixedWidth(120)
        self.toggle_btn.clicked.connect(self._on_toggle_clicked)
        mid_zone.addWidget(self.toggle_btn)

        mid_zone.addStretch()  # 内容靠左，右侧留弹性
        layout.addLayout(mid_zone, 3)

        # ---- 右侧区域（对应右栏=运行日志，占 2 份 stretch）----
        # 信息左对齐 → 起始位置正好与日志栏左缘齐平
        right_zone = QHBoxLayout()
        right_zone.setSpacing(8)
        right_zone.setContentsMargins(0, 0, 0, 0)

        # 连接点 + 连接状态
        self.conn_dot = CaptionLabel("●")
        self.conn_dot.setStyleSheet("color: #c0c0c0; font-size: 14px;")
        right_zone.addWidget(self.conn_dot)

        self.conn_label = BodyLabel("未连接")
        self.conn_label.setStyleSheet("color: #888;")
        right_zone.addWidget(self.conn_label)

        sep1 = CaptionLabel("·")
        sep1.setStyleSheet("color: #bbb;")
        right_zone.addWidget(sep1)

        # 当前任务
        task_label = CaptionLabel("当前任务:")
        task_label.setStyleSheet("color: #999;")
        right_zone.addWidget(task_label)

        self.task_label = BodyLabel("无")
        self.task_label.setStyleSheet("color: #666;")
        right_zone.addWidget(self.task_label)

        sep2 = CaptionLabel("·")
        sep2.setStyleSheet("color: #bbb;")
        right_zone.addWidget(sep2)

        # 已执行时间
        self.elapsed_label = CaptionLabel("")
        self.elapsed_label.setStyleSheet("color: #999;")
        right_zone.addWidget(self.elapsed_label)

        right_zone.addStretch()  # 右区右侧留弹性
        layout.addLayout(right_zone, 2)

        self._start_callback = None
        self._stop_callback = None

        # 任务持续执行计时
        self._elapsed_seconds = 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

    # -------- 外部 API（保持原有语义） --------

    def set_start_callback(self, cb) -> None:
        self._start_callback = cb

    def set_stop_callback(self, cb) -> None:
        self._stop_callback = cb

    # -------- 状态更新槽 --------

    def _on_connect_status(self, ok: bool, msg: str) -> None:
        self._connected = ok
        if ok:
            self.conn_dot.setStyleSheet("color: #4caf50; font-size: 14px;")
            self.conn_label.setText("已连接")
            self.conn_label.setStyleSheet("color: #4caf50;")
        else:
            self.conn_dot.setStyleSheet("color: #f44336; font-size: 14px;")
            self.conn_label.setText("未连接")
            self.conn_label.setStyleSheet("color: #f44336;")
        self._update_toggle_btn()

    def _on_task_started(self, task_name: str) -> None:
        self._running = True
        self._current_task = task_name
        self.task_label.setText(TASK_NAMES.get(task_name, task_name))
        self._elapsed_seconds = 0
        self.elapsed_label.setText("已执行 00:00")
        self._timer.start()
        self._update_toggle_btn()

    def _on_task_finished(self, success: bool) -> None:
        self._running = False
        self._current_task = None
        self.task_label.setText("无")
        self.elapsed_label.setText("")
        self._timer.stop()
        self._update_toggle_btn()

    def _on_tick(self) -> None:
        self._elapsed_seconds += 1
        m, s = divmod(self._elapsed_seconds, 60)
        h, m = divmod(m, 60)
        if h:
            self.elapsed_label.setText(f"已执行 {h:02d}:{m:02d}:{s:02d}")
        else:
            self.elapsed_label.setText(f"已执行 {m:02d}:{s:02d}")

    # -------- 开始/停止 单按钮切换 --------

    def _update_toggle_btn(self) -> None:
        """根据运行状态 + 连接状态刷新切换按钮的文字与可用性。"""
        if self._running:
            self.toggle_btn.setText("停止")
            self.toggle_btn.setEnabled(True)
        else:
            self.toggle_btn.setText("开始")
            self.toggle_btn.setEnabled(self._connected)

    def _on_toggle_clicked(self) -> None:
        """点击合并按钮：运行中则停止，未运行则开始。"""
        if self._running:
            self._on_stop()
        else:
            self._on_start()

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
