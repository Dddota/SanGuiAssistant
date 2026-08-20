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

from app.core import config
from app.core.config import (
    get_zg_city_list, save_zg_city_list,
    get_zg_max_time, save_zg_max_time,
    get_zg_max_attacks, save_zg_max_attacks,
    get_role_alias, set_role_alias,
    get_role_priority_address, save_role_priority_address,
    get_role_teams, save_role_teams,
    current_identity, set_current_identity,
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
        # 当前角色身份（命名空间）。默认取进程级当前身份。
        self._identity = config.current_identity() or ""

        self._init_ui()
        if self._runner is not None:
            self._runner.zg_teams.connect(self._on_teams_read)
            self._runner.zg_identity.connect(self._on_identity_resolved)

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

        # 当前角色/区服 只读显示
        role_row = QHBoxLayout()
        role_row.setSpacing(8)
        self.zg_role_label = BodyLabel(self._identity or "尚未识别角色")
        self.zg_role_label.setToolTip("角色来源：从大地图 OCR 识别，连接成功后自动尝试一次")
        role_row.addWidget(BodyLabel("当前角色/区服："))
        role_row.addWidget(self.zg_role_label)
        role_row.addStretch()
        lay.addLayout(role_row)

        # 角色备注/别名（可选）：设置后作为该角色配置的命名空间，避免同名撞车
        alias_row = QHBoxLayout()
        alias_row.setSpacing(8)
        self.zg_alias_edit = LineEdit()
        self.zg_alias_edit.setPlaceholderText("角色备注/别名（可选，区分同名角色）")
        self.zg_alias_edit.setFixedWidth(200)
        alias_row.addWidget(self.zg_alias_edit)
        self.zg_alias_save_btn = PushButton("保存别名")
        self.zg_alias_save_btn.clicked.connect(self._on_save_alias)
        alias_row.addWidget(self.zg_alias_save_btn)
        alias_row.addStretch()
        lay.addLayout(alias_row)

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

        # 优先级地址（可选，Phase 3 消费）
        pri_addr_row = QHBoxLayout()
        pri_addr_row.setSpacing(8)
        pri_addr_row.addWidget(BodyLabel("优先级地址："))
        self.zg_priority_addr = LineEdit()
        self.zg_priority_addr.setPlaceholderText("可指定优先攻打的地图地址（如：洛阳）")
        self.zg_priority_addr.editingFinished.connect(self._on_priority_addr_changed)
        pri_addr_row.addWidget(self.zg_priority_addr, 1)
        lay.addLayout(pri_addr_row)

        r2 = QHBoxLayout()
        r2.setSpacing(8)
        r2.addWidget(BodyLabel("最大耗时(秒,超过则放弃)"))
        self.zg_max_time = LineEdit()
        self.zg_max_time.setText(str(get_zg_max_time(self._identity)))
        self.zg_max_time.setFixedWidth(80)
        self.zg_max_time.textChanged.connect(self._on_zg_max_time_changed)
        r2.addWidget(self.zg_max_time)
        r2.addStretch()
        lay.addLayout(r2)

        r3 = QHBoxLayout()
        r3.setSpacing(8)
        r3.addWidget(BodyLabel("累计攻打上限"))
        self.zg_max_attacks = LineEdit()
        self.zg_max_attacks.setText(str(get_zg_max_attacks(self._identity)))
        self.zg_max_attacks.setFixedWidth(60)
        self.zg_max_attacks.textChanged.connect(self._on_zg_max_attacks_changed)
        r3.addWidget(self.zg_max_attacks)
        r3.addStretch()
        lay.addLayout(r3)

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
            params["max_cost_time"] = int(
                self.zg_max_time.text().strip() or "600"
            )
        except ValueError:
            pass
        try:
            params["max_attacks"] = int(self.zg_max_attacks.text().strip() or "20")
        except ValueError:
            pass
        addr = self.zg_priority_addr.text().strip()
        if addr:
            params["priority_address"] = addr
        checked = [cb.text() for cb in self._team_boxes if cb.isChecked()]
        if checked:
            params["team_names"] = checked
        return params

    # ---------------- 角色身份相关 ----------------

    def set_identity(self, identity: str) -> None:
        """切换当前角色身份并重载该角色的全局设置。"""
        new_id = config.sanitize_identity(identity or "")
        if not new_id or new_id == "_unknown":
            set_current_identity(identity or "")
            new_id = current_identity()
        self._identity = new_id or ""
        self._reload_for_identity()

    def _reload_for_identity(self) -> None:
        """身份切换后：重载角色名显示、别名、地点、ratio、max_time、优先级地址。"""
        ident = self._identity
        self.zg_role_label.setText(ident or "尚未识别角色")
        self.zg_alias_edit.blockSignals(True)
        self.zg_alias_edit.setText(get_role_alias(ident))
        self.zg_alias_edit.blockSignals(False)

        # 重载城市列表
        self.zg_city_list.blockSignals(True)
        self.zg_city_list.clear()
        for city in get_zg_city_list(ident):
            item = QListWidgetItem(city["name"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if city["checked"]
                else Qt.CheckState.Unchecked
            )
            self.zg_city_list.addItem(item)
        self.zg_city_list.blockSignals(False)

        self.zg_priority_addr.blockSignals(True)
        self.zg_priority_addr.setText(get_role_priority_address(ident))
        self.zg_priority_addr.blockSignals(False)

        self.zg_max_time.blockSignals(True)
        self.zg_max_time.setText(str(get_zg_max_time(ident)))
        self.zg_max_time.blockSignals(False)

        self.zg_max_attacks.blockSignals(True)
        self.zg_max_attacks.setText(str(get_zg_max_attacks(ident)))
        self.zg_max_attacks.blockSignals(False)

        # 重载勾选队伍（优先用该角色已存储的队伍名作为回显候选）
        prev_checked = {cb.text() for cb in self._team_boxes if cb.isChecked()}
        saved = get_role_teams(ident)
        if saved and not prev_checked:
            prev_checked = {n for n in saved if n}
        self._rebuild_team_checkboxes(prev_checked)

    def _on_identity_resolved(self, ident: dict | None) -> None:
        """角色探测结果回调（连接成功 auto-probe，或手动）。"""
        if not ident or not ident.get("role"):
            return
        set_current_identity(ident["role"])
        self.set_identity(ident["role"])

    def _on_save_alias(self) -> None:
        ident = self._identity
        if not ident:
            return
        alias = self.zg_alias_edit.text().strip()
        set_role_alias(ident, alias)
        logger.info("已保存角色别名 %r -> %r", ident, alias)

    def _on_priority_addr_changed(self) -> None:
        ident = self._identity
        if not ident:
            return
        save_role_priority_address(ident, self.zg_priority_addr.text().strip())

    # ---------------- 战功地点列表（增删勾选 + 持久化） ----------------

    def _load_zg_city_list(self) -> None:
        self.zg_city_list.blockSignals(True)
        for city in get_zg_city_list(self._identity):
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
        state = self._zg_city_state()
        save_zg_city_list(
            self._identity,
            [c["name"] for c in state],
            [c["name"] for c in state if c["checked"]],
        )

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

    def _on_zg_max_time_changed(self, text: str) -> None:
        try:
            save_zg_max_time(self._identity, int(text.strip() or "600"))
        except ValueError:
            pass

    def _on_zg_max_attacks_changed(self, text: str) -> None:
        try:
            save_zg_max_attacks(self._identity, int(text.strip() or "20"))
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

    def _rebuild_team_checkboxes(self, prev_checked: set[str]) -> None:
        """从该角色已持久化/历史勾选的队伍名重建勾选区域。

        用于身份切换后回显勾选，无需重新从大地图读取；无持久化队伍时显示提示。
        """
        while self.zg_team_lay.count():
            item = self.zg_team_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._team_boxes = []
        saved = [n for n in get_role_teams(self._identity) if n]

        if not saved:
            self.zg_team_hint = BodyLabel(
                "尚未读取队伍，点击上方「读取队伍」从大地图读取")
            self.zg_team_lay.addWidget(self.zg_team_hint)
            return

        # 没有显式 prev_checked 时，用该角色已持久化的队名作为默认勾选
        effective = prev_checked if prev_checked else set(saved)
        for name in saved:
            cb = CheckBox(name)
            cb.setChecked(name in effective)
            self._team_boxes.append(cb)
            self.zg_team_lay.addWidget(cb)
        self.zg_team_lay.addStretch()

    def _on_teams_read(self, teams: list) -> None:
        self.zg_read_teams_btn.setEnabled(True)

        prev_checked = {cb.text() for cb in self._team_boxes if cb.isChecked()} \
            or {n for n in get_role_teams(self._identity) if n}

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

        # 持久化到当前角色命名空间。此槽在 GUI 主线程执行（信号队列投递，
        # worker 线程不访问 QSettings，避免并发触发原生崩溃）。
        if self._identity:
            save_role_teams(self._identity, [c.text() for c in self._team_boxes])

    def _build_trade(self) -> dict:
        params = {}
        params["use_focus_list"] = self.tr_focus.isChecked()
        manual = self.tr_items.text().strip()
        if manual:
            params["focus_items"] = [
                n.strip() for n in manual.split(",") if n.strip()
            ]
        return params