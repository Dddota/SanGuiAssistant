"""自动刷战功 Tab。"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QTextEdit,
    QProgressBar, QLineEdit, QLabel,
)
from qfluentwidgets import (
    PrimaryPushButton, PushButton, CardWidget, BodyLabel,
    TitleLabel, SubtitleLabel, InfoBar, InfoBarPosition,
    CheckBox, ScrollArea,
)

from app.core.task_runner import TaskRunner

logger = logging.getLogger("sangui.gui")


class ZhanGongTab(QWidget):
    """自动刷战功：在大地图优先攻打『敌众我寡且距离近』的城池战事。"""

    def __init__(self, runner: TaskRunner, parent=None):
        super().__init__(parent)
        self.setObjectName("zhanGongTab")
        self.parent_window = parent
        self.runner = runner
        self._connected = False
        self._team_boxes: list[CheckBox] = []

        self._init_ui()
        self.runner.status.connect(self._on_connect_status)
        self.runner.zg_progress.connect(self._on_progress)
        self.runner.zg_done.connect(self._on_done)
        self.runner.zg_teams.connect(self._on_teams_read)

    def _on_connect_status(self, ok: bool, msg: str) -> None:
        if ok:
            self._connected = True
            self.status_label.setText("状态：已连接模拟器")
            self.start_btn.setEnabled(True)
            self.read_teams_btn.setEnabled(True)
            self._append_log("已连接 MuMu Player 12")
            self._append_log("资源加载完成")
        else:
            self._connected = False
            self.status_label.setText(f"状态：连接失败 - {msg}")
            self.start_btn.setEnabled(False)
            self.read_teams_btn.setEnabled(False)
            self._append_log(f"连接失败: {msg}")

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        title = TitleLabel("自动刷战功")
        layout.addWidget(title)

        subtitle = SubtitleLabel("大地图优先攻打敌众我寡且距离近的城池战事")
        subtitle.setStyleSheet("color: #666;")
        layout.addWidget(subtitle)

        # 优先城市配置
        opt_card = CardWidget()
        opt_layout = QVBoxLayout(opt_card)
        opt_layout.setContentsMargins(20, 15, 20, 15)
        opt_layout.setSpacing(8)

        opt_label = BodyLabel("优先城市（逗号分隔，命中则优先攻打）")
        opt_layout.addWidget(opt_label)

        self.priority_edit = QLineEdit()
        self.priority_edit.setPlaceholderText("例如：洛阳,长安,许昌")
        opt_layout.addWidget(self.priority_edit)

        ratio_row = QHBoxLayout()
        ratio_row.setSpacing(8)
        ratio_row.addWidget(BodyLabel("敌我兵力倍率阈值(默认2倍):"))
        self.ratio_edit = QLineEdit("2")
        self.ratio_edit.setFixedWidth(60)
        ratio_row.addWidget(self.ratio_edit)
        self.max_time_edit = QLineEdit("600")
        self.max_time_edit.setFixedWidth(60)
        ratio_row.addWidget(BodyLabel("最大耗时(秒,超过则放弃):"))
        ratio_row.addWidget(self.max_time_edit)
        ratio_row.addStretch()
        opt_layout.addLayout(ratio_row)

        # 队伍勾选面板
        team_label_row = QHBoxLayout()
        team_label_row.setSpacing(8)
        team_label_row.addWidget(BodyLabel("出战队伍（勾选要使用的队伍）："))
        self.read_teams_btn = PushButton("读取队伍")
        self.read_teams_btn.clicked.connect(self._on_read_teams)
        self.read_teams_btn.setEnabled(False)
        team_label_row.addWidget(self.read_teams_btn)
        team_label_row.addStretch()
        opt_layout.addLayout(team_label_row)

        self.team_scroll = ScrollArea()
        self.team_scroll.setWidgetResizable(True)
        self.team_scroll.setFixedHeight(120)
        self.team_scroll_container = QWidget()
        self.team_scroll_layout = QVBoxLayout(self.team_scroll_container)
        self.team_scroll_layout.setContentsMargins(4, 4, 4, 4)
        self.team_scroll_layout.setSpacing(4)
        self.team_scroll.setWidget(self.team_scroll_container)
        self.team_hint = BodyLabel("尚未读取队伍，点击上方「读取队伍」从大地图读取")
        self.team_scroll_layout.addWidget(self.team_hint)
        opt_layout.addWidget(self.team_scroll)

        self.auto_supply_cb = CheckBox("自动补兵（兵力不足时自动补兵再打）")
        self.auto_supply_cb.setChecked(True)
        opt_layout.addWidget(self.auto_supply_cb)

        layout.addWidget(opt_card)

        # 状态卡片
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

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.start_btn = PrimaryPushButton("开始刷战功")
        self.start_btn.clicked.connect(self._on_start)
        self.start_btn.setEnabled(False)

        self.stop_btn = PushButton("停止")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)

        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 日志区
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

    def _build_params(self) -> dict:
        """从 UI 读取参数。"""
        params: dict = {}
        priority = self.priority_edit.text().strip()
        if priority:
            cities = [c.strip() for c in priority.split(",") if c.strip()]
            params["priority_cities"] = cities
        try:
            ratio = float(self.ratio_edit.text().strip() or "2")
            params["enemy_ratio"] = ratio
        except ValueError:
            pass
        try:
            max_time = int(self.max_time_edit.text().strip() or "600")
            params["max_cost_time"] = max_time
        except ValueError:
            pass
        # 勾选的出战队伍
        checked = [cb.text() for cb in self._team_boxes
                   if cb.isChecked()] if getattr(self, "_team_boxes", None) else []
        if checked:
            params["team_names"] = checked
        params["auto_supply"] = self.auto_supply_cb.isChecked()
        return params

    def _on_read_teams(self) -> None:
        """读取大地图右侧玩家队伍列表，生成勾选复选框。"""
        if not self._connected:
            return
        if self.runner.running:
            self._append_log("任务执行中，无法读取队伍")
            return
        self.read_teams_btn.setEnabled(False)
        self._append_log("读取队伍列表中...")
        self.runner.read_my_teams_async()

    def _on_teams_read(self, teams: list) -> None:
        """队伍读取结果：重新生成勾选复选框。"""
        self.read_teams_btn.setEnabled(True)

        # 记住之前勾选的队伍名
        prev_checked = {cb.text() for cb in self._team_boxes if cb.isChecked()}

        # 清空旧复选框
        while self.team_scroll_layout.count():
            item = self.team_scroll_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self._team_boxes = []
        if not teams:
            empty = BodyLabel("未读取到队伍，请确认当前在【大地图】页面")
            self.team_scroll_layout.addWidget(empty)
            self._append_log("未读取到队伍")
            return

        for t in teams:
            name = t.get("name", "?")
            cb = CheckBox(name)
            cb.setChecked(name in prev_checked)
            self._team_boxes.append(cb)
            self.team_scroll_layout.addWidget(cb)

        self.team_scroll_layout.addStretch()
        names = "、".join(t.get("name", "?") for t in teams)
        self._append_log(f"读取到 {len(teams)} 支队伍：{names}")

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
        self.status_label.setText("状态：刷战功中...")
        self._append_log("=" * 40)
        self._append_log("开始执行战功任务")
        self._append_log("请确保当前停留在【大地图】页面")

        self.runner.start_zhan_gong(self._build_params())

    def _on_stop(self) -> None:
        if self.runner.running:
            self.runner.stop()
            self._append_log("已请求停止")

    def _on_progress(self, msg: str) -> None:
        self._append_log(msg)

    def _on_done(self, success: bool) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setValue(100 if success else 0)

        if success:
            self.status_label.setText("状态：战功刷取完成")
            InfoBar.success(
                title="完成",
                content="战功刷取执行完毕",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
        else:
            self.status_label.setText("状态：任务失败/已停止")
            InfoBar.warning(
                title="警告",
                content="战功任务未完成或已停止",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )