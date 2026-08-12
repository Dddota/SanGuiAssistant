"""主窗口。"""
from __future__ import annotations

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from qfluentwidgets import NavigationItemPosition, MSFluentWindow

from app.core.task_runner import TaskRunner
from app.view.debug_tab import DebugTab
from app.view.guixin_tab import GuixinTab
from app.view.peijiang_tab import PeijiangTab
from app.view.settings_tab import SettingsTab
from app.view.sinan_tab import SinanTab
from app.view.status_bar import GlobalStatusBar


class MainWindow(MSFluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("三归小助手")
        self.resize(900, 650)

        # 全局共享唯一的 TaskRunner：保证同一时刻只执行一个任务（归心/司南/配将互斥）
        self.runner = TaskRunner()

        self.guixin_tab = GuixinTab(self.runner, self)
        self.sinan_tab = SinanTab(self.runner, self)
        self.peijiang_tab = PeijiangTab(self)
        self.settings_tab = SettingsTab(self.runner, self)
        self.debug_tab = DebugTab(self.runner, self)

        self.addSubInterface(
            self.guixin_tab,
            QIcon(),
            "一键归心",
            position=NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.sinan_tab,
            QIcon(),
            "自动司南",
            position=NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.peijiang_tab,
            QIcon(),
            "智能配将台",
            position=NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.settings_tab,
            QIcon(),
            "设置",
            position=NavigationItemPosition.BOTTOM,
        )
        self.addSubInterface(
            self.debug_tab,
            QIcon(),
            "调试",
            position=NavigationItemPosition.BOTTOM,
        )

        # 将 stackWidget 包进垂直布局，底部挂全局状态栏
        vbox = QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        vbox.addWidget(self.stackedWidget, 1)
        self.status_bar = GlobalStatusBar(self.runner, self)
        vbox.addWidget(self.status_bar)
        self.hBoxLayout.removeWidget(self.stackedWidget)
        self.hBoxLayout.addLayout(vbox, 1)

        # 启动后异步建立模拟器连接（真实任务执行时由 TaskRunner 自持 controller）
        self.runner.connect_async()