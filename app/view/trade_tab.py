"""辅助交易 Tab。"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QTextEdit,
    QTableWidget, QTableWidgetItem, QLineEdit, QAbstractItemView,
    QListWidget, QListWidgetItem, QHeaderView,
)
from qfluentwidgets import (
    PrimaryPushButton, PushButton, CardWidget, BodyLabel,
    TitleLabel, SubtitleLabel, InfoBar, InfoBarPosition,
    CheckBox,
)

from app.core.task_runner import TaskRunner

logger = logging.getLogger("sangui.gui")


class TradeTab(QWidget):
    """辅助交易：自动扫描交易行中关注物品的上架与求购信息。"""

    def __init__(self, runner: TaskRunner, parent=None):
        super().__init__(parent)
        self.setObjectName("tradeTab")
        self.parent_window = parent
        self.runner = runner
        self._connected = False
        self._items: list = []

        self._init_ui()
        self.runner.status.connect(self._on_connect_status)
        self.runner.trade_progress.connect(self._on_progress)
        self.runner.trade_done.connect(self._on_done)
        self.runner.trade_result.connect(self._on_result)

    def _on_connect_status(self, ok: bool, msg: str) -> None:
        if ok:
            self._connected = True
            self.status_label.setText("状态：已连接模拟器")
            self.start_btn.setEnabled(True)
            self._append_log("已连接 MuMu Player 12")
            self._append_log("资源加载完成")
        else:
            self._connected = False
            self.status_label.setText(f"状态：连接失败 - {msg}")
            self.start_btn.setEnabled(False)
            self._append_log(f"连接失败: {msg}")

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        title = TitleLabel("辅助交易")
        layout.addWidget(title)

        subtitle = SubtitleLabel("自动扫描交易行中关注物品的上架与求购信息")
        subtitle.setStyleSheet("color: #666;")
        layout.addWidget(subtitle)

        # 配置卡片
        opt_card = CardWidget()
        opt_layout = QVBoxLayout(opt_card)
        opt_layout.setContentsMargins(20, 15, 20, 15)
        opt_layout.setSpacing(8)

        self.use_focus_cb = CheckBox("从游戏内『关注』列表读取物品")
        self.use_focus_cb.setChecked(True)
        opt_layout.addWidget(self.use_focus_cb)

        manual_row = QHBoxLayout()
        manual_row.setSpacing(8)
        manual_row.addWidget(BodyLabel("手动物品（逗号分隔，兜底）："))
        self.focus_edit = QLineEdit()
        self.focus_edit.setPlaceholderText("例如：玄铁,丝绸,青铜")
        manual_row.addWidget(self.focus_edit, 1)
        opt_layout.addLayout(manual_row)

        layout.addWidget(opt_card)

        # 状态卡片
        status_card = CardWidget()
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(20, 15, 20, 15)
        status_layout.setSpacing(10)

        self.status_label = BodyLabel("状态：未连接")
        status_layout.addWidget(self.status_label)
        layout.addWidget(status_card)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.start_btn = PrimaryPushButton("开始扫描")
        self.start_btn.clicked.connect(self._on_start)
        self.start_btn.setEnabled(False)

        self.stop_btn = PushButton("停止")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)

        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 结果区：左侧物品列表 + 右侧盘口表格
        result_split = QHBoxLayout()
        result_split.setSpacing(12)

        # 左：物品列表
        left_card = CardWidget()
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)
        left_layout.addWidget(BodyLabel("物品"))
        self.item_list = QListWidget()
        self.item_list.setMinimumWidth(140)
        self.item_list.setMaximumWidth(200)
        self.item_list.currentItemChanged.connect(self._on_item_selected)
        left_layout.addWidget(self.item_list)
        result_split.addWidget(left_card, 0)

        # 右：盘口表格
        right_card = CardWidget()
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setSpacing(0)
        buy_hdr = BodyLabel("求购（买）")
        buy_hdr.setStyleSheet("color: #2e7d32; font-weight: bold;")
        center_hdr = BodyLabel("")
        center_hdr.setFixedWidth(60)
        sell_hdr = BodyLabel("出售（卖）")
        sell_hdr.setStyleSheet("color: #c62828; font-weight: bold;")
        header_row.addStretch(1)
        header_row.addWidget(buy_hdr)
        header_row.addWidget(center_hdr)
        header_row.addWidget(sell_hdr)
        header_row.addStretch(1)
        right_layout.addLayout(header_row)

        # 盘口表格：求购档 | 分隔 | 出售档（类似股票买卖盘）
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["求购价格", "求购数量", "", "出售数量", "出售价格"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(220)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        right_layout.addWidget(self.table)
        result_split.addWidget(right_card, 1)
        layout.addLayout(result_split)

        # 日志区
        log_label = BodyLabel("运行日志")
        layout.addWidget(log_label)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(200)
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
        params["use_focus_list"] = self.use_focus_cb.isChecked()
        manual = self.focus_edit.text().strip()
        if manual:
            names = [n.strip() for n in manual.split(",") if n.strip()]
            params["focus_items"] = names
        return params

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
        self.status_label.setText("状态：扫描中...")
        self._append_log("=" * 40)
        self._append_log("开始执行辅助交易扫描")
        self._append_log("请确保当前停留在【主界面】")

        self.runner.start_trade(self._build_params())

    def _on_stop(self) -> None:
        if self.runner.running:
            self.runner.stop()
            self._append_log("已请求停止")

    def _on_progress(self, msg: str) -> None:
        self._append_log(msg)

    def _on_result(self, items: list) -> None:
        """扫描结果：填充物品列表，并展示第一个物品的盘口。"""
        self._items = items
        self.item_list.clear()
        for it in items:
            QListWidgetItem(it.get("name", "?"), self.item_list)
        if items:
            self.item_list.setCurrentRow(0)
            self._render_book(items[0])

    def _on_item_selected(self, current: QListWidgetItem, previous=None) -> None:
        """切换物品时刷新盘口表格。"""
        if current is None:
            return
        name = current.text()
        for it in getattr(self, "_items", []):
            if it.get("name") == name:
                self._render_book(it)
                break

    def _render_book(self, item: dict) -> None:
        """在盘口表格里渲染一个物品的求购/出售挂单（类似股票买卖盘）。

        布局：求购档（价格高→低）在上，出售档（价格低→高）在下，
        两侧分别展示数量与价格，中间留空列作分隔。
        """
        buy_levels = item.get("buy_levels", [])
        sell_levels = item.get("sell_levels", [])
        rows = max(len(buy_levels), len(sell_levels), 1)
        self.table.setRowCount(rows)

        # 求购方向显示：价格从高到低（buy_levels 已在引擎排序）
        for i, lv in enumerate(buy_levels):
            self.table.setItem(i, 0, QTableWidgetItem(str(lv.get("price", ""))))
            self.table.setItem(i, 1, QTableWidgetItem(str(lv.get("count", ""))))
        # 出售方向显示：价格从低到高（sell_levels 已在引擎排序）
        for i, lv in enumerate(sell_levels):
            self.table.setItem(i, 3, QTableWidgetItem(str(lv.get("count", ""))))
            self.table.setItem(i, 4, QTableWidgetItem(str(lv.get("price", ""))))

        # 空档补 "-"
        for i in range(rows):
            for col in (0, 1, 3, 4):
                if self.table.item(i, col) is None:
                    self.table.setItem(i, col, QTableWidgetItem("-"))

    def _on_done(self, success: bool) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        if success:
            self.status_label.setText("状态：扫描完成")
            InfoBar.success(
                title="完成",
                content="辅助交易扫描完毕",
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
                content="辅助交易任务未完成或已停止",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )