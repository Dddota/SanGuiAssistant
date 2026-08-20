"""主窗口：MSFluentWindow 多页导航。

导航项：
- 主页（TOP）：三栏式主界面（左任务清单 + 中设置 + 右共享日志）+ 底部状态栏
- 设置（BOTTOM）：连接参数与软件更新
- 调试（BOTTOM）：模板匹配识别

所有页面通过 MSFluentWindow 自带的 stackedWidget 在窗口内切换，不再弹 QDialog。
"""
from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QVBoxLayout, QApplication, QWidget

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

        # 注册到 MSFluentWindow 导航子页面（内部加入 stackedWidget 并创建导航项）
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

    # ---------- 页面构建 ----------

    def _init_home_page(self) -> None:
        """主页：三栏主体（Dashboard 内左/中/右）+ 底部状态栏。"""
        vbox = QVBoxLayout(self.home_page)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # 三栏主体（左任务清单 + 中设置 + 右日志，均在 Dashboard 内部，保证齐平）
        self.dashboard = Dashboard(self.runner, self.log_panel)
        vbox.addWidget(self.dashboard, 1)

        # 底部状态栏（齿轮已移至 Dashboard 左栏底部，此处只保留开始/停止 + 状态信息）
        self.status_bar = GlobalStatusBar(self.runner, self)
        vbox.addWidget(self.status_bar)
        self.status_bar.set_start_callback(self.dashboard._on_start)
        self.status_bar.set_stop_callback(self.dashboard._on_stop)

        # 收尾动作工作线程请求退出 → 主线程安全退出
        self.dashboard.quit_requested.connect(self._quit_app_delayed)

    def _init_settings_page(self) -> None:
        """设置页：SettingsTab（共用 log_panel 用于更新日志输出）。"""
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