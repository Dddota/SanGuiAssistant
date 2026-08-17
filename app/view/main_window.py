"""主窗口：三栏式布局，参照明日方舟 MAA。

左栏：可勾选的功能任务清单（Dashboard 内）。
中栏：选中功能的参数设置 + 开始/停止（Dashboard 内）。
右栏：共享日志系统。
底部：全局连接/任务状态栏。
设置与调试保留在底部导航。
"""
from __future__ import annotations

from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QDialog

from qfluentwidgets import NavigationItemPosition, MSFluentWindow, FluentIcon

from app.core.task_runner import TaskRunner
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
        self.settings_tab = SettingsTab(self.runner, self)
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

    def _open_settings_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("设置")
        dlg.resize(520, 420)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        tab = SettingsTab(self.runner, dlg)
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