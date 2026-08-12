"""调试 Tab：识别结果面板。"""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QTextEdit, QComboBox,
)
from qfluentwidgets import (
    CardWidget, TitleLabel, SubtitleLabel, BodyLabel,
    PrimaryPushButton, InfoBar, InfoBarPosition, ComboBox,
)

from app.core import config
from app.core.task_runner import TaskRunner

logger = logging.getLogger("sangui.gui")


class DebugTab(QWidget):
    def __init__(self, runner: TaskRunner, parent=None):
        super().__init__(parent)
        self.setObjectName("debugTab")
        self.parent_window = parent
        self.runner = runner

        self._init_ui()
        self._load_templates()
        self.runner.status.connect(self._on_connect_status)
        self.runner.recognition.connect(self._on_recognition)

    def _template_dir(self) -> Path:
        return Path(config.get_connection_params()["resource_path"]) / "image"

    def _load_templates(self) -> None:
        d = self._template_dir()
        if d.exists():
            names = sorted(p.name for p in d.glob("*.png"))
            self.template_combo.clear()
            self.template_combo.addItems(names)
        else:
            self._append_result(f"模板目录不存在: {d}")

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        title = TitleLabel("调试")
        layout.addWidget(title)

        subtitle = SubtitleLabel("选择模板并对当前屏幕做模板匹配识别")
        subtitle.setStyleSheet("color: #666;")
        layout.addWidget(subtitle)

        card = CardWidget()
        row = QHBoxLayout(card)
        row.setContentsMargins(20, 15, 20, 15)
        row.setSpacing(10)

        self.template_combo = ComboBox()
        self.template_combo.setMinimumWidth(220)

        self.recognize_btn = PrimaryPushButton("识别")
        self.recognize_btn.clicked.connect(self._on_recognize)

        row.addWidget(BodyLabel("模板"))
        row.addWidget(self.template_combo)
        row.addWidget(self.recognize_btn)
        row.addStretch()
        layout.addWidget(card)

        result_label = BodyLabel("识别结果")
        layout.addWidget(result_label)

        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setMinimumHeight(300)
        self.result_view.setStyleSheet(
            "QTextEdit { background: #f7f7f7; border: 1px solid #e0e0e0; "
            "border-radius: 8px; padding: 8px; font-family: Consolas, monospace; }"
        )
        layout.addWidget(self.result_view)

        layout.addStretch()

    def _append_result(self, msg: str) -> None:
        self.result_view.append(msg)
        self.result_view.verticalScrollBar().setValue(
            self.result_view.verticalScrollBar().maximum()
        )

    def _on_connect_status(self, ok: bool, msg: str) -> None:
        if ok:
            self._append_result("已连接模拟器，可进行识别")
        else:
            self._append_result(f"连接失败: {msg}")

    def _on_recognition(self, text: str) -> None:
        self._append_result(text)

    def _on_recognize(self) -> None:
        template = self.template_combo.currentText()
        if not template:
            InfoBar.warning(
                title="提示",
                content="请选择模板",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self,
            )
            return
        self._append_result(f"识别模板: {template}")
        self.runner.recognize_async(template)