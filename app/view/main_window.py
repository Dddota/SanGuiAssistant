"""主窗口：MSFluentWindow 多页导航。

导航项：
- 主页（TOP）：三栏式主界面（左任务清单 + 中设置 + 右日志）+ 底部状态栏
- 设置（BOTTOM）：连接参数与软件更新
- 调试（BOTTOM）：模板匹配识别

所有页面通过 MSFluentWindow 自带的 stackedWidget 在窗口内切换，不再弹 QDialog。
"""
from __future__ import annotations

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QMessageBox, QApplication,
)

from qfluentwidgets import NavigationItemPosition, MSFluentWindow, FluentIcon

from app import __version__, __app_name__
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
        self._base_title = f"{__app_name__} SGA v{__version__}"
        self.setWindowTitle(self._base_title)
        self.resize(1280, 760)

        # 全局共享唯一的 TaskRunner：保证同一时刻只执行一个任务（互斥）
        self.runner = TaskRunner()

        # 共享日志面板（主页与设置页共用，跨页面保留日志内容）
        self.log_panel = LogPanel()

        # ---- 构建三个子页面 ----
        self.home_page = QWidget()
        self.home_page.setObjectName("home")
        self._init_home_page()

        self.settings_page = QWidget()
        self.settings_page.setObjectName("settings")
        self._init_settings_page()

        self.debug_page = QWidget()
        self.debug_page.setObjectName("debug")
        self._init_debug_page()

        # 注册为 MSFluentWindow 导航子页面（内部加入 stackedWidget 并创建导航项）
        self.addSubInterface(
            self.home_page, FluentIcon.HOME, "主页",
            position=NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.settings_page, FluentIcon.SETTING, "设置",
            position=NavigationItemPosition.BOTTOM,
        )
        self.addSubInterface(
            self.debug_page, FluentIcon.DEVELOPER_TOOLS, "调试",
            position=NavigationItemPosition.BOTTOM,
        )

        # 启动后异步建立模拟器连接
        self.runner.connect_async()
        self.runner.status.connect(self._on_connect_status)

        # 启动时在后台自动检查一次更新
        self._setup_auto_check_update()

    # ---------- 页面构造 ----------

    def _init_home_page(self) -> None:
        """主页：三栏主体（Dashboard 内含左/中/右）+ 底部状态栏。"""
        vbox = QVBoxLayout(self.home_page)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # 三栏主体（左任务清单 + 中设置 + 右日志，均在 Dashboard 内部，保证齐平）
        self.dashboard = Dashboard(self.runner, self.log_panel)
        vbox.addWidget(self.dashboard, 1)

        # 底部状态栏（完成后齿轮已移至 Dashboard 左栏底部，此处只保留开始/停止 + 状态信息）
        self.status_bar = GlobalStatusBar(self.runner, self)
        vbox.addWidget(self.status_bar)
        self.status_bar.set_start_callback(self.dashboard._on_start)
        self.status_bar.set_stop_callback(self.dashboard._on_stop)

        # 收尾动作工作线程请求退出 → 主线程安全退出
        self.dashboard.quit_requested.connect(self._quit_app_delayed)

    def _init_settings_page(self) -> None:
        """设置页：SettingsTab（共享 log_panel 用于更新日志输出）。"""
        lay = QVBoxLayout(self.settings_page)
        lay.setContentsMargins(0, 0, 0, 0)
        self.settings_tab = SettingsTab(self.runner, self, log_panel=self.log_panel)
        lay.addWidget(self.settings_tab)

    def _init_debug_page(self) -> None:
        """调试页：DebugTab。"""
        lay = QVBoxLayout(self.debug_page)
        lay.setContentsMargins(0, 0, 0, 0)
        self.debug_tab = DebugTab(self.runner, self)
        lay.addWidget(self.debug_tab)

    # ---------- 回调 ----------

    def _quit_app_delayed(self) -> None:
        """收尾动作请求退出：在主线程延迟片刻，让日志/提示刷新后再退出。"""
        QTimer.singleShot(2000, QApplication.quit)

    def _on_connect_status(self, connected: bool, msg: str) -> None:
        """连接状态变化时更新标题，追加已连接模拟器地址（含端口）。"""
        if connected:
            from app.core import config
            addr = config.get_connection_params()["address"]
            self.setWindowTitle(f"{self._base_title} · 已连接 {addr}")
        else:
            self.setWindowTitle(self._base_title)

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
            return  # 用户此前已选择"稍后"，本次忽略
        self._prompt_update(info)

    def _ignored_update_version(self) -> str:
        """读取上次用户选择"稍后"时忽略的版本号（跨启动保持）。"""
        s = QSettings()
        return s.value("update/ignored_version", "", type=str)

    def _prompt_update(self, info: dict) -> None:
        """弹窗询问是否更新；点"更新"则后台应用并退出，"稍后"忽略该版本。"""
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
            QTimer.singleShot(2000, QApplication.quit)
        elif box.clickedButton() is later_btn:
            # 记住本版本，避免每次启动弹窗打扰
            QSettings().setValue("update/ignored_version", tag)

    def _on_auto_apply_done(self, ok: bool, msg: str) -> None:
        """自动更新结束：失败提示；成功已由 quit 接管流程。"""
        if not ok:
            QMessageBox.warning(self, "更新失败", msg)
