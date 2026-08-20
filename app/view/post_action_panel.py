"""完成后动作多选设置面板（参照明日方舟 MAA 交互）。"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import (
    CardWidget, TitleLabel, BodyLabel, CheckBox,
)

from app.core import config
from app.core.post_action import POST_ACTIONS

logger = logging.getLogger("sangui.gui")


class PostActionPanel(CardWidget):
    """中栏：任务结束后动作的多选设置面板。

    每个动作一个 CheckBox，可同时勾选多个；勾选变化立即持久化。
    通过 actions_changed 信号通知外部刷新状态栏摘要。
    """

    actions_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checkboxes: list[tuple[CheckBox, str]] = []  # (widget, key)
        self._loading = False
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(16)

        self.title_label = TitleLabel("完成后")
        layout.addWidget(self.title_label)

        self.desc_label = BodyLabel("全部任务执行完毕后要做的事，可多选")
        self.desc_label.setStyleSheet("color: #666;")
        layout.addWidget(self.desc_label)

        # 复选框列表
        self._check_container = QWidget()
        check_lay = QVBoxLayout(self._check_container)
        check_lay.setContentsMargins(4, 4, 4, 4)
        check_lay.setSpacing(12)

        for key, label in POST_ACTIONS:
            cb = CheckBox(label)
            cb.setProperty("action_key", key)
            cb.toggled.connect(self._on_toggled)
            self._checkboxes.append((cb, key))
            check_lay.addWidget(cb)

        check_lay.addStretch()
        layout.addWidget(self._check_container, 1)

    # ---------------- public ----------------

    def load(self, actions: list[str]) -> None:
        """从外部动作列表加载勾选状态，期间不触发保存信号。"""
        self._loading = True
        try:
            action_set = set(actions or [])
            for cb, key in self._checkboxes:
                cb.blockSignals(True)
                cb.setChecked(key in action_set)
                cb.blockSignals(False)
        finally:
            self._loading = False

    def checked_actions(self) -> list[str]:
        """返回当前勾选的动作键列表（按 POST_ACTIONS 顺序）。"""
        return [key for cb, key in self._checkboxes if cb.isChecked()]

    # ---------------- internal ----------------

    def _on_toggled(self, _checked: bool) -> None:
        if self._loading:
            return
        actions = self.checked_actions()
        config.save_post_actions(actions)
        self.actions_changed.emit(actions)
        logger.info("已保存完成后动作：%s", actions or ["无"])
