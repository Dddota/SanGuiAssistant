"""主窗口：三栏式布局，参照明日方舟 MAA。

左栏：可勾选的功能任务清单（Dashboard 内）。
中栏：选中功能的参数设置 + 开始/停止（Dashboard 内）。
右栏：共享日志系统。
底部：全局连接/任务状态栏。
设置与调试保留在底部导航。
"""
from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QDialog, QApplication

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
        """启动时后台检查一次更新；发现新版本则自动进入更新流程。"""
        self.update_worker = UpdateWorker()  # 持有引用防止被 GC
        self.update_worker.check_done.connect(self._on_auto_check_done)
        self.update_worker.check_error.connect(self._on_auto_check_error)
        self.update_worker.check()

    def _on_auto_check_error(self, msg: str) -> None:
        """自动检查失败：写入日志，不打扰用户。"""
        self.log_panel.append(f"自动检查更新失败：{msg}")

    def _on_auto_check_done(self, info: dict) -> None:
        """自动检查结束：若发现新版本则直接自动更新，不再弹窗询问。"""
        if not info or not info.get("tag"):
            return  # 无更新或网络错误，静默
        tag = info.get("tag", "")
        self._apply_update_now(info)

    def _apply_update_now(self, info: dict) -> None:
        """直接应用更新（下载→应用→自动重启）。供启动自动检查调用。"""
        tag = info.get("tag", "")
        # 应用更新：后台下载并应用，进度通过日志面板展示，
        # 完成后由 apply_done 回调安排退出（更新脚本接管替换并重启）。
        self.update_worker.apply(info)
        self.update_worker.apply_byte_progress.connect(
            self._on_auto_apply_byte_progress
        )
        self.update_worker.apply_done.connect(self._on_auto_apply_done)
        self.log_panel.append(
            f"发现新版本 {tag}（当前 v{__version__}），正在自动更新："
            f"下载并应用更新包，完成后程序将自动重启。"
        )

    def _on_auto_apply_byte_progress(self, downloaded: int, total: int) -> None:
        """自动更新字节进度：低频写入日志面板（每满 ~5% 记一次）。"""
        if total <= 0:
            if getattr(self, "_auto_last_pct", None) is None:
                self._auto_last_pct = 0
            self.log_panel.append(
                f"下载进度：{downloaded / 1048576:.0f} MB (下载中...)"
            )
            return
        pct = downloaded / total * 100 if total else 0
        # 每满 ~5% 才记一次日志，避免日志爆炸
        cur = int(pct // 5)
        last = getattr(self, "_auto_last_pct", -1)
        if cur == last:
            return
        self._auto_last_pct = cur
        self.log_panel.append(
            f"下载进度：{downloaded / 1048576:.1f} MB / "
            f"{total / 1048576:.1f} MB ({pct:.0f}%)"
        )

    def _on_auto_apply_done(self, ok: bool, msg: str) -> None:
        """自动更新结束：成功延迟退出（更新脚本接管重启）；失败仅写日志，不退出。"""
        if ok:
            self.log_panel.append(f"更新已启动：{msg}")
            # 延迟让界面（日志/进度）刷新后退出，更新脚本接管替换并重启
            QTimer.singleShot(1500, QApplication.quit)
        else:
            # 失败仅记录日志，不弹窗；程序保持当前可用状态继续运行
            self.log_panel.append(f"更新失败：{msg}（当前程序仍可正常使用）")