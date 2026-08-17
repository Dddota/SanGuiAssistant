"""中栏：选中任务的具体设置面板。

三个 Tab 的独立参数（司南/归心无参数、战功/交易有参数）统一收敛到这里，
在选择左栏任务时切换显示对应配置卡片，并可即时修改。
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QStackedWidget,
    QListWidget, QListWidgetItem,
)
from qfluentwidgets import (
    BodyLabel, TitleLabel, SubtitleLabel, CardWidget, PrimaryPushButton,
    PushButton, CheckBox, LineEdit, ScrollArea,
)

from app.core.config import (
    get_zg_city_list, save_zg_city_list, get_zg_ratio, save_zg_ratio,
    get_zg_max_time, save_zg_max_time,
)

logger = logging.getLogger("sangui.gui")


class TaskSettingsPanel(CardWidget):
    """中栏：显示选中任务的说明 + 可编辑参数。

    开始/停止统一在底部全局状态栏操作，这里只管参数配置。
    """

    def __init__(self, runner, params_fn, parent=None):
        super().__init__(parent)
        self._runner = runner  # 用于读取战功队伍等运行时交互
        self._params_fn = params_fn  # (key) -> dict，由 BatchPanel 提供
        self._current_key = None
        self._team_boxes: list[CheckBox] = []

        self._init_ui()
        if self._runner is not None:
            self._runner.zg_teams.connect(self._on_teams_read)

    # ---------------- public ----------------

    def show_task(self, key: str, name: str, desc: str) -> None:
        """切换到某个任务的设置面板。"""
        self._current_key = key
        self.title_label.setText(name)
        self.desc_label.setText(desc)
        self._stack.setCurrentWidget(self._panel_for(key))

    def build_params(self) -> dict:
        """收集当前选中（显示）任务的参数。"""
        return self.build_params_for(self._current_key)

    def build_params_for(self, key: str) -> dict:
        """按任务 key 收集参数，不依赖面板当前显示哪个任务。

        所有子面板在 _init_ui 中无条件构建，控件始终存在，因此可对任意
        勾选并运行的任务读取其参数，避免被勾选任务与中栏停留任务不一致时
        参数整体落空（否则 priority_cities 会退化成引擎默认值）。
        """
        if key == "zhan_gong":
            return self._build_zhan_gong()
        if key == "trade":
            return self._build_trade()
        return {}

    # ---------------- UI ----------------

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        self.title_label = TitleLabel("请选择任务")
        layout.addWidget(self.title_label)

        self.desc_label = SubtitleLabel("在左侧勾选任务并点击开始")
        self.desc_label.setStyleSheet("color: #666;")
        layout.addWidget(self.desc_label)

        # 参数区：一个 QStackedWidget，按任务切换
        self._no_arg_panel = self._card("此任务无需额外配置，勾选后即可一键执行。")
        self._stack = QStackedWidget()
        self._stack.addWidget(self._no_arg_panel)

        # 战功参数子面板
        self._build_zhan_gong_panel()
        self._stack.addWidget(self._zhan_gong_panel)

        # 交易参数子面板
        self._build_trade_panel()
        self._stack.addWidget(self._trade_panel)

        layout.addWidget(self._stack, 1)

    def _card(self, text: str) -> QWidget:
        card = QWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(4, 4, 4, 4)
        lbl = BodyLabel(text)
        lbl.setStyleSheet("color: #888;")
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        lay.addStretch()
        return card

    # ---------------- 战功参数 ----------------

    def _build_zhan_gong_panel(self) -> None:
        p = QWidget()
        lay = QVBoxLayout(p)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(10)

        # 战功地点列表：可增删勾选，勾选命中则自动优先攻打
        lay.addWidget(BodyLabel("战功地点（勾选命中则自动优先攻打）："))
        self.zg_city_list = QListWidget()
        self.zg_city_list.setFixedHeight(110)
        self._load_zg_city_list()
        lay.addWidget(self.zg_city_list)

        city_row = QHBoxLayout()
        city_row.setSpacing(8)
        self.zg_city_input = LineEdit()
        self.zg_city_input.setPlaceholderText("输入地点名，回车添加")
        self.zg_city_input.returnPressed.connect(self._add_zg_city)
        self.zg_city_add_btn = PushButton("添加")
        self.zg_city_add_btn.clicked.connect(self._add_zg_city)
        self.zg_city_del_btn = PushButton("删除选中")
        self.zg_city_del_btn.clicked.connect(self._del_zg_city)
        city_row.addWidget(self.zg_city_input, 1)
        city_row.addWidget(self.zg_city_add_btn)
        city_row.addWidget(self.zg_city_del_btn)
        lay.addLayout(city_row)

        r1 = QHBoxLayout()
        r1.setSpacing(8)
        r1.addWidget(BodyLabel("敌我兵力倍率阈值"))
        self.zg_ratio = LineEdit()
        self.zg_ratio.setText(str(get_zg_ratio()))
        self.zg_ratio.setFixedWidth(60)
        self.zg_ratio.textChanged.connect(self._on_zg_ratio_changed)
        r1.addWidget(self.zg_ratio)
        r1.addStretch()
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(8)
        r2.addWidget(BodyLabel("最大耗时(秒,超过则放弃)"))
        self.zg_max_time = LineEdit()
        self.zg_max_time.setText(str(get_zg_max_time()))
        self.zg_max_time.setFixedWidth(80)
        self.zg_max_time.textChanged.connect(self._on_zg_max_time_changed)
        r2.addWidget(self.zg_max_time)
        r2.addStretch()
        lay.addLayout(r2)

        # 出战队伍：读取 + 勾选
        team_label = QHBoxLayout()
        team_label.setSpacing(8)
        team_label.addWidget(BodyLabel("出战队伍（勾选要使用的队伍）："))
        self.zg_read_teams_btn = PushButton("读取队伍")
        self.zg_read_teams_btn.setEnabled(False)
        self.zg_read_teams_btn.clicked.connect(self._on_read_teams)
        team_label.addWidget(self.zg_read_teams_btn)
        team_label.addStretch()
        lay.addLayout(team_label)

        self.zg_team_scroll = ScrollArea()
        self.zg_team_scroll.setWidgetResizable(True)
        self.zg_team_scroll.setFixedHeight(110)
        self.zg_team_container = QWidget()
        self.zg_team_lay = QVBoxLayout(self.zg_team_container)
        self.zg_team_lay.setContentsMargins(4, 4, 4, 4)
        self.zg_team_lay.setSpacing(4)
        self.zg_team_hint = BodyLabel("尚未读取队伍，点击上方「读取队伍」从大地图读取")
        self.zg_team_lay.addWidget(self.zg_team_hint)
        self.zg_team_scroll.setWidget(self.zg_team_container)
        lay.addWidget(self.zg_team_scroll)

        lay.addStretch()
        self._zhan_gong_panel = p

    def _build_trade_panel(self) -> None:
        p = QWidget()
        lay = QVBoxLayout(p)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(10)

        self.tr_focus = CheckBox("从游戏内『关注』列表读取物品")
        self.tr_focus.setChecked(True)
        lay.addWidget(self.tr_focus)

        r = QHBoxLayout()
        r.setSpacing(8)
        r.addWidget(BodyLabel("手动物品（逗号分隔，兜底）："))
        self.tr_items = LineEdit()
        self.tr_items.setPlaceholderText("例如：玄铁,丝绸,青铜")
        r.addWidget(self.tr_items, 1)
        lay.addLayout(r)

        lay.addStretch()
        self._trade_panel = p

    # ---------------- 参数收集 ----------------

    def _panel_for(self, key: str) -> QWidget:
        if key == "zhan_gong":
            return self._zhan_gong_panel
        if key == "trade":
            return self._trade_panel
        return self._no_arg_panel

    def _build_zhan_gong(self) -> dict:
        params: dict = {}
        checked = self._checked_zg_cities()
        if checked:
            params["priority_cities"] = checked
        try:
            params["enemy_ratio"] = float(self.zg_ratio.text().strip() or "2")
        except ValueError:
            pass
        try:
            params["max_cost_time"] = int(
                self.zg_max_time.text().strip() or "600"
            )
        except ValueError:
            pass
        checked = [cb.text() for cb in self._team_boxes if cb.isChecked()]
        if checked:
            params["team_names"] = checked
        return params

    # ---------------- 战功地点列表（增删勾选 + 持久化） ----------------

    def _load_zg_city_list(self) -> None:
        self.zg_city_list.blockSignals(True)
        for city in get_zg_city_list():
            item = QListWidgetItem(city["name"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if city["checked"]
                else Qt.CheckState.Unchecked
            )
            self.zg_city_list.addItem(item)
        self.zg_city_list.blockSignals(False)
        self.zg_city_list.itemChanged.connect(self._on_zg_city_changed)

    def _add_zg_city(self) -> None:
        name = self.zg_city_input.text().strip()
        if not name:
            return
        for i in range(self.zg_city_list.count()):
            if self.zg_city_list.item(i).text() == name:
                self.zg_city_input.clear()
                return
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        self.zg_city_list.addItem(item)
        self.zg_city_input.clear()
        self._persist_zg_cities()

    def _del_zg_city(self) -> None:
        for item in self.zg_city_list.selectedItems():
            self.zg_city_list.takeItem(self.zg_city_list.row(item))
        self._persist_zg_cities()

    def _on_zg_city_changed(self, _item) -> None:
        self._persist_zg_cities()

    def _persist_zg_cities(self) -> None:
        save_zg_city_list(self._zg_city_state())

    def _checked_zg_cities(self) -> list[str]:
        return [c["name"] for c in self._zg_city_state() if c["checked"]]

    def _zg_city_state(self) -> list[dict]:
        out = []
        for i in range(self.zg_city_list.count()):
            item = self.zg_city_list.item(i)
            out.append({
                "name": item.text(),
                "checked": item.checkState() == Qt.CheckState.Checked,
            })
        return out

    def _on_zg_ratio_changed(self, text: str) -> None:
        try:
            save_zg_ratio(float(text.strip() or "2"))
        except ValueError:
            pass

    def _on_zg_max_time_changed(self, text: str) -> None:
        try:
            save_zg_max_time(int(text.strip() or "600"))
        except ValueError:
            pass

    # ---------------- 出战队伍（读取 + 勾选） ----------------

    def set_can_read_teams(self, enabled: bool) -> None:
        """连接可用时允许读取队伍。"""
        if hasattr(self, "zg_read_teams_btn"):
            self.zg_read_teams_btn.setEnabled(enabled)

    def _on_read_teams(self) -> None:
        if not self._runner or not self._runner.running:
            self.zg_read_teams_btn.setEnabled(False)
            self._runner.read_my_teams_async()

    def _on_teams_read(self, teams: list) -> None:
        self.zg_read_teams_btn.setEnabled(True)

        prev_checked = {cb.text() for cb in self._team_boxes if cb.isChecked()}

        while self.zg_team_lay.count():
            item = self.zg_team_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self._team_boxes = []
        if not teams:
            self.zg_team_lay.addWidget(
                BodyLabel("未读取到队伍，请确认当前在【大地图】页面"))
            return

        for t in teams:
            name = t.get("name", "?")
            cb = CheckBox(name)
            cb.setChecked(name in prev_checked)
            self._team_boxes.append(cb)
            self.zg_team_lay.addWidget(cb)
        self.zg_team_lay.addStretch()

    def _build_trade(self) -> dict:
        params = {}
        params["use_focus_list"] = self.tr_focus.isChecked()
        manual = self.tr_items.text().strip()
        if manual:
            params["focus_items"] = [
                n.strip() for n in manual.split(",") if n.strip()
            ]
        return params