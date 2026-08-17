"""设置 Tab：连接参数可编辑并持久化。"""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QLineEdit, QFormLayout,
)
from qfluentwidgets import (
    CardWidget, TitleLabel, SubtitleLabel, BodyLabel,
    PrimaryPushButton, PushButton, InfoBar, InfoBarPosition,
    LineEdit,
)

from app.core import config
from app.core.task_runner import TaskRunner

logger = logging.getLogger("sangui.gui")


class SettingsTab(QWidget):
    def __init__(self, runner: TaskRunner, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsTab")
        self.parent_window = parent
        self.runner = runner

        self._init_ui()
        self._load_params()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        title = TitleLabel("设置")
        layout.addWidget(title)

        subtitle = SubtitleLabel("配置模拟器连接参数")
        subtitle.setStyleSheet("color: #666;")
        layout.addWidget(subtitle)

        card = CardWidget()
        form = QFormLayout(card)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(15)

        self.adb_path_edit = LineEdit()
        self.adb_path_edit.setPlaceholderText("adb.exe 完整路径")

        self.detect_adb_btn = PushButton("自动检测")
        self.detect_adb_btn.clicked.connect(self._on_detect_adb)
        adb_row = QHBoxLayout()
        adb_row.setSpacing(8)
        adb_row.addWidget(self.adb_path_edit, 1)
        adb_row.addWidget(self.detect_adb_btn)

        self.address_edit = LineEdit()
        self.address_edit.setPlaceholderText("127.0.0.1:16384")

        self.resource_edit = LineEdit()
        self.resource_edit.setPlaceholderText("app/assets")

        form.addRow(BodyLabel("ADB 路径"), adb_row)
        form.addRow(BodyLabel("模拟器地址"), self.address_edit)
        form.addRow(BodyLabel("资源目录"), self.resource_edit)
        layout.addWidget(card)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.save_btn = PrimaryPushButton("保存并重连")
        self.save_btn.clicked.connect(self._on_save)
        self.reset_btn = PushButton("恢复默认")
        self.reset_btn.clicked.connect(self._on_reset)
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.reset_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        hint = BodyLabel("修改参数后点击\"保存并重连\"，将断开旧连接并按新参数重新连接。")
        hint.setStyleSheet("color: #999;")
        layout.addWidget(hint)

        layout.addStretch()

    def _load_params(self) -> None:
        params = config.get_connection_params()
        self.adb_path_edit.setText(params["adb_path"])
        self.address_edit.setText(params["address"])
        self.resource_edit.setText(params["resource_path"])

    def _collect(self) -> tuple:
        return (
            self.adb_path_edit.text().strip(),
            self.address_edit.text().strip(),
            self.resource_edit.text().strip(),
        )

    def _on_save(self) -> None:
        adb_path, address, resource_path = self._collect()
        if not adb_path or not address or not resource_path:
            InfoBar.error(
                title="错误",
                content="连接参数不能为空",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
            return

        config.save_connection_params(adb_path, address, resource_path)
        self.runner.reconnect(adb_path, address, resource_path)
        InfoBar.success(
            title="已保存",
            content="连接参数已保存，正在重新连接...",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self,
        )

    def _on_reset(self) -> None:
        self.adb_path_edit.setText(config.ADB_PATH)
        self.address_edit.setText(config.ADB_ADDRESS)
        self.resource_edit.setText(config.RESOURCE_PATH)

    def _on_detect_adb(self) -> None:
        """自动探测本机 adb.exe 并填入路径框。"""
        found = config.detect_adb()
        self.adb_path_edit.setText(found)
        if Path(found).is_file():
            InfoBar.success(
                title="已检测",
                content=f"找到 adb：{found}",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
        else:
            InfoBar.warning(
                title="未找到",
                content="未探测到常见模拟器的 adb，请手动填写路径。",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )