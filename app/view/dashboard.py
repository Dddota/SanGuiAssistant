"""主仪表盘（三栏式左 + 中）。

左栏：可勾选的任务清单（与 MAA 类似），勾选后一键按顺序执行。
中栏：选中任务的说明 + 可编辑参数 + 开始/停止。
二者经本类的 BatchRunner 驱动，进度统一转发到右侧 LogPanel。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QListWidget, QListWidgetItem,
    QStackedWidget,
)
from qfluentwidgets import (
    CardWidget, BodyLabel, PrimaryPushButton, PushButton, InfoBar,
    InfoBarPosition, CheckBox, ToolButton, FluentIcon,
)

from app.core.features import TASKS, TASK_NAMES, BatchRunner
from app.core import config
from app.core.config import (
    get_selected_tasks, save_selected_tasks, get_last_task, save_last_task,
)
from app.view.log_panel import LogPanel
from app.view.settings_panel import TaskSettingsPanel
from app.view.post_action_panel import PostActionPanel


class TaskListCard(CardWidget):
    """左栏可勾选任务清单。"""

    task_selected = pyqtSignal(str)  # 选中了某个任务（用于切换中栏面板）
    config_edit = pyqtSignal(str)    # 点击某任务行的齿轮，要求打开其配置面板

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._tasks = []

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        layout.addWidget(BodyLabel("选择任务"))
        self.list = QListWidget()
        self.list.setStyleSheet("QListWidget { border: none; }")
        layout.addWidget(self.list, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.select_all_btn = PushButton("全选")
        self.select_none_btn = PushButton("全不选")
        self.select_all_btn.clicked.connect(self._select_all)
        self.select_none_btn.clicked.connect(self._select_none)
        btn_row.addWidget(self.select_all_btn)
        btn_row.addWidget(self.select_none_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def set_tasks(self, tasks) -> None:
        self.list.clear()
        self._tasks = []
        saved = set(get_selected_tasks())
        for t in tasks:
            item = QListWidgetItem()
            cb = CheckBox(t.name)
            cb.setProperty("task_key", t.key)
            cb.setToolTip(t.desc)
            cb.setChecked(t.key in saved)
            # 勾选框仅切换勾选状态并持久化，不再切换配置面板；
            # 配置面板改由每行的齿轮按钮打开。
            cb.clicked.connect(lambda _c, key=t.key: self._persist_selection())
            gear = ToolButton(FluentIcon.SETTING)
            gear.setProperty("task_key", t.key)
            gear.setToolTip(f"配置{t.name}")
            gear.setFixedSize(24, 24)
            gear.clicked.connect(lambda _c, key=t.key: self.config_edit.emit(key))

            # 每行：勾选框 + 弹性占位 + 齿轮，水平布局
            row = QWidget()
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 4, 8, 4)  # 右侧 8px 留给齿轮，避免贴边
            row_lay.setSpacing(8)
            row_lay.addWidget(cb)
            row_lay.addStretch()
            row_lay.addWidget(gear)

            # 放大任务行字号
            font = cb.font()
            font.setPointSize(11)
            cb.setFont(font)
            cb.ensurePolished()
            # 显式固定每行高度（layout 未激活时 row.sizeHint() 为 0，会把行压没）
            row.setFixedHeight(40)
            # 宽度留足：卡片内容区约 208px (240 - 16*2)，item 宽度设略小确保齿轮完整显示
            item.setSizeHint(QSize(200, 40))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            self._tasks.append((cb, t))

    def restore_last_task(self) -> None:
        """恢复上次打开/选中的任务面板（需在信号绑定后调用）。"""
        last = get_last_task()
        if last and any(t.key == last for _cb, t in self._tasks):
            self.task_selected.emit(last)
        elif self._tasks:
            self.task_selected.emit(self._tasks[0][1].key)

    def checked_keys(self) -> list[str]:
        out = []
        for cb, t in self._tasks:
            if cb.isChecked():
                out.append(t.key)
        return out

    def _persist_selection(self) -> None:
        save_selected_tasks(self.checked_keys())

    def _select_all(self) -> None:
        for cb, _t in self._tasks:
            cb.setChecked(True)
        self._persist_selection()

    def _select_none(self) -> None:
        for cb, _t in self._tasks:
            cb.setChecked(False)
        self._persist_selection()


class Dashboard(QWidget):
    """三栏式主页面：左（任务清单）+ 中（参数设置 / 完成后）+ 右（运行日志）。

    三栏在同一 layout 里，共用一套 padding 与 spacing，保证顶部、底部、卡片高度齐平。
    """

    post_actions_changed = pyqtSignal(list)
    quit_requested = pyqtSignal()  # 收尾动作在工作线程请求退出，经队列信号回到主线程

    def __init__(self, runner, log_panel: LogPanel | None = None, parent=None):
        super().__init__(parent)
        self.runner = runner
        # 允许外部传入共享 LogPanel 实例（跨页共用）；未传则内部创建
        self.log_panel = log_panel if log_panel is not None else LogPanel()
        self._connected = False
        self._post_open = False

        self.batch = BatchRunner(runner)

        self._init_ui()
        self._bind_signals()
        self.task_list.restore_last_task()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # 左栏：任务清单卡片 + 下方完成后动作（纵向排列，整体固定 240px 宽）
        left_col = QVBoxLayout()
        left_col.setSpacing(12)
        left_col.setContentsMargins(0, 0, 0, 0)

        self.task_list = TaskListCard()
        self.task_list.set_tasks(TASKS)
        left_col.addWidget(self.task_list, 1)

        # 完成后动作卡片（贴在任务清单下方，同宽，与整体卡片风格一致）
        self.post_bar = CardWidget()
        post_bar_lay = QHBoxLayout(self.post_bar)
        post_bar_lay.setContentsMargins(12, 10, 12, 10)
        post_bar_lay.setSpacing(8)

        post_label = BodyLabel("完成后")
        post_label.setStyleSheet("color: #999;")
        post_bar_lay.addWidget(post_label)

        self.post_summary = BodyLabel("无动作")
        self.post_summary.setStyleSheet("color: #666;")
        post_bar_lay.addWidget(self.post_summary, 1)

        self.post_gear = ToolButton(FluentIcon.SETTING)
        self.post_gear.setCheckable(True)
        self.post_gear.setToolTip("完成后动作设置")
        self.post_gear.clicked.connect(self.toggle_post_action_panel)
        post_bar_lay.addWidget(self.post_gear)

        left_col.addWidget(self.post_bar, 0)

        # 把左栏整体放进一个容器 widget，保持 240px 固定宽度
        left_container = QWidget()
        left_container.setFixedWidth(240)
        left_container.setLayout(left_col)
        layout.addWidget(left_container, 0)

        # 中栏：QStackedWidget 切换任务参数 / 完成后设置（卡片由内部面板提供）
        self.settings = TaskSettingsPanel(self.runner, self._params_fn)
        self._post_panel = PostActionPanel()
        self._middle_stack = QStackedWidget()
        self._middle_stack.addWidget(self.settings)     # index 0：任务参数
        self._middle_stack.addWidget(self._post_panel)  # index 1：完成后设置
        self._middle_stack.setCurrentIndex(0)
        layout.addWidget(self._middle_stack, 3)

        # 右栏：运行日志卡片（与左、中栏同处一个 layout，天然上下齐平）
        layout.addWidget(self.log_panel, 2)

    # noqa
    def _bind_signals(self) -> None:
        self.runner.status.connect(self._on_connect_status)
        self.batch.log.connect(self.log_panel.append)
        self.batch.task_started.connect(self._on_task_started)
        self.batch.batch_finished.connect(self._on_batch_finished)
        self.batch.task_finished.connect(self._on_task_finished)
        # 点击任务清单切换中栏设置
        self.task_list.task_selected.connect(self._on_task_selected)
        # 点任务行齿轮 → 打开对应任务的配置面板
        self.task_list.config_edit.connect(self._on_task_selected)
        # 点任务名（勾选框）只负责勾选，不再切换配置面板
        # 完成后动作变化 → 刷新左栏底部摘要 + 转发到外部
        self._post_panel.actions_changed.connect(self._on_post_actions_changed)
        # 初始加载完成后动作
        self._post_panel.load(config.get_post_actions())
        self._refresh_post_summary(config.get_post_actions())

    def _on_task_selected(self, key: str) -> None:
        name = TASK_NAMES.get(key, key)
        t = next((t for t in TASKS if t.key == key), None)
        desc = t.desc if t else ""
        self.settings.show_task(key, name, desc)
        save_last_task(key)
        self.task_list._persist_selection()

    # ---------------- 连接状态 ----------------

    def _on_connect_status(self, ok: bool, msg: str) -> None:
        self._connected = ok
        self.settings.set_can_read_teams(ok)
        if ok:
            self.log_panel.append("已连接 MuMu Player 12")
            self.log_panel.append("资源加载完成")
        else:
            self.log_panel.append(f"连接失败: {msg}")

    # ---------------- 运行控制 ----------------

    def _params_fn(self, key: str) -> dict:
        # 按任务 key 读取参数，与中栏当前显示哪个任务无关
        return self.settings.build_params_for(key)

    def _on_start(self) -> None:
        if not self._connected:
            InfoBar.error(
                title="错误", content="未连接模拟器",
                orient=Qt.Orientation.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self,
            )
            return
        keys = self.task_list.checked_keys()
        if not keys:
            InfoBar.warning(
                title="提示", content="请先在左侧勾选要执行的任务",
                orient=Qt.Orientation.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self,
            )
            return
        self.log_panel.append("开始一键执行所选任务...")
        self.batch.start(keys, self._params_fn)
        for cb, t in self.task_list._tasks:
            cb.setEnabled(False)

    def _on_stop(self) -> None:
        self.batch.stop()
        self.log_panel.append("已请求停止")

    def _on_task_started(self, key: str) -> None:
        name = TASK_NAMES.get(key, key)
        self.log_panel.append(f"正在执行：{name}")

    def _on_task_finished(self, key: str, ok: bool) -> None:
        pass

    def toggle_post_action_panel(self, open_: bool | None = None) -> bool:
        """翻转/设置中栏显示完成后设置面板。返回新的开启状态。

        open_=True  显示设置页
        open_=False 回任务参数页
        open_=None  翻转
        """
        if open_ is None:
            open_ = not self._post_open
        if open_ == self._post_open:
            return open_
        self._post_open = open_
        next_idx = 1 if open_ else 0
        self._middle_stack.setCurrentIndex(next_idx)
        # 同步齿轮选中态
        try:
            self.post_gear.setChecked(open_)
        except Exception:
            pass
        return open_

    def _on_post_actions_changed(self, actions: list[str]) -> None:
        """完成后动作变化：刷新左栏底部摘要 + 转发到外部。"""
        self._refresh_post_summary(actions)
        self.post_actions_changed.emit(actions)

    def _refresh_post_summary(self, actions: list[str]) -> None:
        """刷新左栏底部"完成后"摘要文本。"""
        from app.core.post_action import POST_ACTIONS, label_of
        if not actions:
            self.post_summary.setText("无动作")
            return
        text = "、".join(
            label_of(a) for a in actions if a in dict(POST_ACTIONS)
        )
        self.post_summary.setText(text if text else "无动作")

    def _maybe_run_post_action(self) -> None:
        import threading

        actions = config.get_post_actions()
        if not actions:
            return

        def _log(msg: str) -> None:
            # 经 batch.log 信号（队列连接）写日志面板，避免从工作线程直接触碰 QTextEdit
            self.batch.log.emit(msg)

        def _quit() -> None:
            # 工作线程不能创建 GUI 定时器；经队列信号回到主线程后再退出。
            # 延后让日志/提示刷新。
            self.quit_requested.emit()

        # 关键：『关机』必须由用户在主线程模态框里显式确认后才真正触发，
        # 绝不能在后台线程预发系统 shutdown。
        # ── 否则系统弹出的是 Windows 自己的关机通知气泡，点"关闭/取消"并不能
        #    取消关机（取消必须 shutdown /a），会导致用户点了取消仍被关机。
        rest = [a for a in actions if a != "shutdown"]

        def _worker() -> None:
            from app.core.post_action import execute
            # rest 已剔掉 shutdown；execute 内部按序 close_emulator → quit(在末尾)
            execute(rest, quit_app=_quit if "quit" in rest else None, log=_log)

        # 主线程：先弹关机确认框（倒计时，可取消），用户确认后才真正关机。
        # 确认框关闭/取消时系统从未发出关机命令 → 必然取消成功。
        if "shutdown" in actions:
            confirmed = self._confirm_shutdown(_log)
            if not confirmed:
                # 用户取消关机 → 视为主张"不要收尾"，放弃其余全部动作
                # （含退出三归小助手/关闭模拟器），避免出现"取消关机后应用仍被关"。
                _log("已取消关机，放弃剩余收尾动作，保持运行")
                return

        # 关机确认结束（若勾了关机）后再执行其余动作 + 退出。
        # 关掉确认框后若无任何动作则直接返回。
        if rest:
            threading.Thread(target=_worker, daemon=True).start()

    def _confirm_shutdown(self, log) -> bool:
        """主线程模态关机倒计时确认框。

        倒计时归零或用户点『立即关机』→ 真发 shutdown /s；返回 True。
        『取消』或直接关窗 → 什么都不发（系统从未收到关机命令 → 必然不关机）；返回 False。
        """
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        )

        total = 60
        state = {"remaining": total, "fired": False}

        dlg = QDialog(self)
        dlg.setWindowTitle("关机确认")
        dlg.setModal(True)
        tip = QLabel("部分收尾动作已完成。是否关机？")
        tip.setWordWrap(True)
        count = QLabel()
        font = count.font()
        font.setPointSize(22)
        font.setBold(True)
        count.setFont(font)
        count.setAlignment(Qt.AlignmentFlag.AlignCenter)

        cancel_btn = QPushButton("取消关机")
        ok_btn = QPushButton("立即关机")

        def _now() -> None:
            # 真正发起关机（用户确认）。发短延时光机，留痕后系统进入关机。
            if state["fired"]:
                return
            state["fired"] = True
            log("用户确认关机，稍后系统将关机...")
            from app.core.post_action import remote_shutdown
            remote_shutdown(log)
            timer.stop() if hasattr(timer, "stop") else None
            dlg.accept()

        def _cancel() -> None:
            # 从未发出关机命令 → 必然取消成功
            if state["fired"]:
                return
            log("已取消关机")
            timer.stop() if hasattr(timer, "stop") else None
            dlg.reject()

        def _tick() -> None:
            state["remaining"] -= 1
            if state["remaining"] <= 0:
                count.setText(f"{0} 秒后关机")
                _now()
            else:
                count.setText(f"{state['remaining']} 秒后关机")

        lay = QVBoxLayout(dlg)
        lay.addWidget(tip)
        lay.addWidget(count)
        count.setText(f"{total} 秒后关机")
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        lay.addLayout(btn_row)

        cancel_btn.clicked.connect(_cancel)
        ok_btn.clicked.connect(_now)
        dlg.rejected.connect(_cancel)  # 按 ESC / 关闭窗口也一律取消关机
        timer = QTimer(dlg)
        timer.setInterval(1000)
        timer.timeout.connect(_tick)
        timer.start()

        dlg.exec()
        return state["fired"]

    def _on_batch_finished(self, success: bool) -> None:
        for cb, _t in self.task_list._tasks:
            cb.setEnabled(True)
        if success:
            self.log_panel.append("全部任务执行完毕")
            InfoBar.success(
                title="完成", content="所选任务已全部执行完毕",
                orient=Qt.Orientation.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self,
            )
            self._maybe_run_post_action()
        else:
            self.log_panel.append("批量执行已停止")
            InfoBar.warning(
                title="提示", content="批量执行已停止",
                orient=Qt.Orientation.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self,
            )