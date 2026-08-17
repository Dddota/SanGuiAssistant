"""主仪表盘（三栏式左 + 中）。

左栏：可勾选的任务清单（与 MAA 类似），勾选后一键按顺序执行。
中栏：选中任务的说明 + 可编辑参数 + 开始/停止。
二者经本类的 BatchRunner 驱动，进度统一转发到右侧 LogPanel。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QListWidget, QListWidgetItem,
)
from qfluentwidgets import (
    CardWidget, BodyLabel, PrimaryPushButton, PushButton, InfoBar,
    InfoBarPosition, CheckBox, FluentIcon,
)

from app.core.features import TASKS, TASK_NAMES, BatchRunner
from app.core.config import (
    get_selected_tasks, save_selected_tasks, get_last_task, save_last_task,
)
from app.view.settings_panel import TaskSettingsPanel


class TaskListCard(CardWidget):
    """左栏可勾选任务清单。"""

    task_selected = pyqtSignal(str)  # 选中了某个任务（用于切换中栏面板）

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
            cb.clicked.connect(lambda _c, key=t.key: self.task_selected.emit(key))
            item.setSizeHint(cb.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, cb)
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
    """三栏式主页面的左 + 中两块：任务清单 + 设置。右侧日志由 main_window 挂载。"""

    def __init__(self, runner, log_panel, parent=None):
        super().__init__(parent)
        self.runner = runner
        self.log_panel = log_panel
        self._connected = False

        self.batch = BatchRunner(runner)

        self._init_ui()
        self._bind_signals()
        self.task_list.restore_last_task()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # 左栏
        self.task_list = TaskListCard()
        self.task_list.setFixedWidth(220)
        self.task_list.set_tasks(TASKS)
        layout.addWidget(self.task_list, 0)

        # 中栏
        self.settings = TaskSettingsPanel(self.runner, self._params_fn)
        layout.addWidget(self.settings, 1)

    # noqa
    def _bind_signals(self) -> None:
        self.runner.status.connect(self._on_connect_status)
        self.batch.log.connect(self.log_panel.append)
        self.batch.task_started.connect(self._on_task_started)
        self.batch.batch_finished.connect(self._on_batch_finished)
        self.batch.task_finished.connect(self._on_task_finished)
        # 点击任务清单切换中栏设置
        self.task_list.task_selected.connect(self._on_task_selected)

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
        # 只有当前设置面板对应的任务才读取参数，其余用空参数
        if getattr(self.settings, "_current_key", None) == key:
            return self.settings.build_params()
        return {}

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
        else:
            self.log_panel.append("批量执行已停止")
            InfoBar.warning(
                title="提示", content="批量执行已停止",
                orient=Qt.Orientation.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self,
            )