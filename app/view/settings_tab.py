"""设置 Tab：连接参数可编辑并持久化。"""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QLineEdit, QFormLayout,
    QApplication,
)
from qfluentwidgets import (
    CardWidget, TitleLabel, SubtitleLabel, BodyLabel,
    PrimaryPushButton, PushButton, InfoBar, InfoBarPosition,
    LineEdit,
)

from app import __version__
from app.core import config
from app.core.task_runner import TaskRunner
from app.core.update_worker import UpdateWorker

logger = logging.getLogger("sangui.gui")


class SettingsTab(QWidget):
    def __init__(self, runner: TaskRunner, parent=None, log_panel=None):
        """log_panel: 可选右侧共享日志面板（存在则把更新进度同步写入）。"""
        super().__init__(parent)
        self.setObjectName("settingsTab")
        self.parent_window = parent
        self.runner = runner
        self._log_panel = log_panel

        # 软件更新 Worker：持有自身引用防止被 GC
        self.worker = UpdateWorker()
        self.worker.check_done.connect(self._on_check_done)
        self.worker.check_error.connect(self._on_check_error)
        self.worker.apply_progress.connect(self._on_apply_progress)
        self.worker.apply_done.connect(self._on_apply_done)
        self._latest_info: dict | None = None  # 最近一次检查到的最新版信息

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

        # ---- 软件更新卡片 ----
        update_card = CardWidget()
        update_lay = QVBoxLayout(update_card)
        update_lay.setContentsMargins(20, 20, 20, 20)
        update_lay.setSpacing(12)
        self._update_lay = update_lay  # 供“立即更新”按钮插入

        update_title = BodyLabel("软件更新")
        update_lay.addWidget(update_title)

        # 第一行：检查更新按钮 + 当前版本
        row = QHBoxLayout()
        row.setSpacing(10)
        self.check_update_btn = PushButton("检查更新")
        self.check_update_btn.clicked.connect(self._on_check_update)
        row.addWidget(self.check_update_btn)
        self.version_label = BodyLabel(f"当前版本 v{__version__}")
        self.version_label.setStyleSheet("color: #666;")
        row.addWidget(self.version_label)
        row.addStretch()
        update_lay.addLayout(row)

        # 第二行：更新状态提示
        self.update_status_label = BodyLabel("已是最新版本")
        self.update_status_label.setStyleSheet("color: #999;")
        update_lay.addWidget(self.update_status_label)

        # 立即更新按钮（发现新版本后才创建并显示）
        self.update_now_btn: PushButton | None = None

        layout.addWidget(update_card)

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

    # ---- 软件更新逻辑 ----

    def _log_to_panel(self, msg: str) -> None:
        """把更新相关消息同步写入右侧共享日志（若存在）。"""
        if self._log_panel is not None and hasattr(self._log_panel, "append"):
            self._log_panel.append(msg)

    def _on_check_update(self) -> None:
        """点击“检查更新”：后台检查，按钮置灰并提示。"""
        self.check_update_btn.setEnabled(False)
        self.update_status_label.setText("正在检查更新...")
        self._log_to_panel("检查更新：正在检查 Gitee 最新版本...")
        self.worker.check()

    def _on_check_done(self, info: dict) -> None:
        """后台检查结束：恢复按钮，按结果提示并（可选）显示“立即更新”。"""
        self.check_update_btn.setEnabled(True)
        if info and info.get("tag"):
            # 发现新版本
            self._latest_info = info
            tag = info.get("tag", "")
            self.update_status_label.setText(f"发现新版本 v{tag}")
            self._log_to_panel(
                f"检查更新：发现新版本 v{tag}（当前 v{__version__}）")
            InfoBar.info(
                title="发现新版本",
                content=f"发现新版本 {tag}，可以立即更新。",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self,
            )
            self._ensure_update_now_btn()
        else:
            # 无更新 / 网络错误
            self._latest_info = None
            self.update_status_label.setText("已是最新版本")
            self._log_to_panel("检查更新：已是最新版本")
            InfoBar.success(
                title="已是最新版本",
                content="当前已是最新版本。",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )

    def _on_check_error(self, msg: str) -> None:
        """检查过程异常兜底。"""
        self.check_update_btn.setEnabled(True)
        self.update_status_label.setText("检查更新失败")
        self._log_to_panel(f"检查更新失败：{msg}")
        InfoBar.error(
            title="检查更新失败",
            content=msg,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self,
        )

    def _ensure_update_now_btn(self) -> None:
        """首次发现新版本时创建“立即更新”按钮。"""
        if self.update_now_btn is not None:
            return
        self.update_now_btn = PushButton("立即更新")
        self.update_now_btn.clicked.connect(self._on_update_now)
        # 插到更新卡片布局末尾（状态标签下方）
        self._update_lay.addWidget(self.update_now_btn)

    def _on_update_now(self) -> None:
        """点击“立即更新”：交后台应用更新。"""
        if self._latest_info is None:
            return
        self.update_now_btn.setEnabled(False)
        self.update_now_btn.setText("更新中...")
        self.update_status_label.setText("正在准备更新...")
        tag = self._latest_info.get("tag", "")
        self._log_to_panel(f"开始更新到 v{tag}：下载更新包...")
        self.worker.apply(self._latest_info)

    def _on_apply_progress(self, msg: str) -> None:
        """更新过程中更新状态标签。"""
        self.update_status_label.setText(msg)
        self._log_to_panel(msg)

    def _on_apply_done(self, ok: bool, msg: str) -> None:
        """更新结束：失败提示；成功则提示并延迟退出主程序。"""
        if ok:
            self.update_status_label.setText(msg)
            self._log_to_panel(f"更新已启动：{msg}")
            InfoBar.success(
                title="更新已启动",
                content=msg,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self,
            )
            # 延迟让界面刷新后退出，更新脚本接管替换并重启
            QTimer.singleShot(1500, QApplication.quit)
        else:
            self.update_status_label.setText("更新失败")
            self._log_to_panel(f"更新失败：{msg}")
            if self.update_now_btn is not None:
                self.update_now_btn.setEnabled(True)
                self.update_now_btn.setText("立即更新")
            InfoBar.error(
                title="更新失败",
                content=msg,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self,
            )