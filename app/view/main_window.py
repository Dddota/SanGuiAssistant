"""主窗口：三栏式布局，参照明日方舟 MAA。

左栏：可勾选的功能任务清单（Dashboard 内）。
中栏：选中功能的参数设置 + 开始/停止（Dashboard 内）。
右栏：共享日志系统。
底部：全局连接/任务状态栏。
设置与调试保留在底部导航。
"""
from __future__ import annotations

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QDialog, QMessageBox

from qfluentwidgets import NavigationItemPosition, MSFluentWindow, FluentIcon

from app import __version__
from app.core.task_runner import TaskRunner
from app.core.update_worker import UpdateWorker
from app.view.dashboard import Dashboard
from app.view.log_panel import LogPanel
from app.view.settings_tab import SettingsTab
from app.view.debug_tab import DebugTab
from app.view.status_bar import GlobalStatusBar


class MainWindow(MSFluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("三归小助手")
        self.resize(1280, 760)

        # 全局共享唯一的 TaskRunner：保证同一时刻只执行一个任务（互斥）
        self.runner = TaskRunner()

        # 三栏主体：左(任务清单) + 中(设置)   +   右(共享日志)
        self.log_panel = LogPanel()
        self.dashboard = Dashboard(self.runner, self.log_panel)

        # 底部导航：设置 / 调试（弹窗形式，主区域为自定义三栏布局）
        self.settings_tab = SettingsTab(self.runner, self, log_panel=self.log_panel)
        self.debug_tab = DebugTab(self.runner, self)
        self.navigationInterface.addItem(
            routeKey="settings",
            icon=FluentIcon.SETTING,
            text="设置",
            position=NavigationItemPosition.BOTTOM,
            onClick=self._open_settings_dialog,
        )
        self.navigationInterface.addItem(
            routeKey="debug",
            icon=FluentIcon.DEVELOPER_TOOLS,
            text="调试",
            position=NavigationItemPosition.BOTTOM,
            onClick=self._open_debug_dialog,
        )

        # 将 stackWidget 包进垂直布局，内部为 三栏横排 + 底部状态栏
        vbox = QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(16)
        columns.addWidget(self.dashboard, 3)   # 左 + 中
        columns.addWidget(self.log_panel, 2)   # 右：日志
        vbox.addLayout(columns, 1)

        self.status_bar = GlobalStatusBar(self.runner, self)
        vbox.addWidget(self.status_bar)
        self.status_bar.set_start_callback(self.dashboard._on_start)
        self.status_bar.set_stop_callback(self.dashboard._on_stop)

        self.hBoxLayout.removeWidget(self.stackedWidget)
        self.hBoxLayout.addLayout(vbox, 1)

        # 启动后异步建立模拟器连接
        self.runner.connect_async()

        # 启动时在后台自动检查一次更新
        self._setup_auto_check_update()

    def _open_settings_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("设置")
        dlg.resize(520, 420)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        tab = SettingsTab(self.runner, dlg, log_panel=self.log_panel)
        lay.addWidget(tab)
        dlg.exec()

    def _open_debug_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("调试")
        dlg.resize(640, 560)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        tab = DebugTab(self.runner, dlg)
        lay.addWidget(tab)
        dlg.exec()

    # ---- 启动自动更新检查 ----

    def _setup_auto_check_update(self) -> None:
        """启动时后台检查一次更新；发现新版本且用户未忽略则弹窗询问。"""
        self.update_worker = UpdateWorker()  # 持有引用防止被 GC
        self.update_worker.check_done.connect(self._on_auto_check_done)
        self.update_worker.check()

    def _on_auto_check_done(self, info: dict) -> None:
        """自动检查结束：若返回用户未忽略的新版本，弹窗询问是否更新。"""
        if not info or not info.get("tag"):
            return  # 无更新或网络错误，静默
        tag = info.get("tag", "")
        if tag == self._ignored_update_version():
            return  # 用户此前已选择“稍后”，本次忽略
        self._prompt_update(info)

    def _ignored_update_version(self) -> str:
        """读取上次用户选择“稍后”时忽略的版本号（跨启动保持）。"""
        s = QSettings()
        return s.value("update/ignored_version", "", type=str)

    def _prompt_update(self, info: dict) -> None:
        """弹窗询问是否更新；点“更新”则后台应用并退出，“稍后”忽略该版本。"""
        tag = info.get("tag", "")
        box = QMessageBox(self)
        box.setWindowTitle("发现新版本")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"发现新版本 v{tag}（当前 v{__version__}）")
        box.setInformativeText("是否立即更新？")
        update_btn = box.addButton("更新", QMessageBox.ButtonRole.AcceptRole)
        later_btn = box.addButton("稍后", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(update_btn)
        box.exec()

        if box.clickedButton() is update_btn:
            # 应用更新并退出主程序（更新脚本接管替换与重启）
            self.update_worker.apply(info)
            self.update_worker.apply_done.connect(self._on_auto_apply_done)
            QMessageBox.information(
                self, "正在更新",
                "正在下载并应用更新，完成后程序将自动重启。",
            )
            from PyQt6.QtCore import QTimer
            from PyQt6.QtWidgets import QApplication
            QTimer.singleShot(2000, QApplication.quit)
        elif box.clickedButton() is later_btn:
            # 记住本版本，避免每次启动弹窗打扰
            QSettings().setValue("update/ignored_version", tag)

    def _on_auto_apply_done(self, ok: bool, msg: str) -> None:
        """自动更新结束：#失败提示；成功已由 quit 接管流程。"""
        if not ok:
            QMessageBox.warning(self, "更新失败", msg)