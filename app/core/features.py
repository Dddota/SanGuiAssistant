"""可一键执行的任务注册表 + 顺序批处理运行器。

三栏式主界面左下角任务清单即来自这里的 TASKS：勾选多个任务后，
BatchRunner 会在后台线程里按顺序逐个执行（归心/司南/战功/交易互斥，
同一时刻只跑一个），并把进度统一转发到右侧共享日志。
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QObject, pyqtSignal


class TaskDef:
    """描述一个可一键执行的任务。"""

    def __init__(self, key: str, name: str, desc: str):
        self.key = key
        self.name = name
        self.desc = desc


TASKS: list[TaskDef] = [
    TaskDef("guixin", "归心", "自动把所有城池的归心次数用完"),
    TaskDef("sinan", "司南", "自动使用所有可用的司南"),
    TaskDef("zhan_gong", "战功", "大地图优先攻打敌众我寡且距离近的城池战事"),
    TaskDef("trade", "交易", "自动扫描交易行中关注物品的上架与求购信息"),
]

TASK_NAMES = {t.key: t.name for t in TASKS}


class BatchRunner(QObject):
    """顺序执行一组任务，通过信号驱动，GUI 线程不阻塞。

    事件流：调用 start(keys) 后逐个启动 TaskRunner 对应的引擎，
    监听各自的 done 信号，成功后继续下一个，直到跑完全部队列。
    """

    log = pyqtSignal(str)           # 共享日志行
    task_started = pyqtSignal(str)  # 当前任务 key
    task_finished = pyqtSignal(str, bool)  # key, success
    batch_started = pyqtSignal()
    batch_finished = pyqtSignal(bool)     # 全部成功(未被打断)为 True

    def __init__(self, runner):
        super().__init__()
        self._runner = runner
        self._keys: list[str] = []
        self._index = -1
        self._running = False
        self._stop = False
        self._wait_done: set[str] = set()
        self._params_fn = None
        self._started_at: float | None = None  # 本次批量启动的单调时钟时间戳

        # 监听所有任务完成信号（done）与引擎进度信号
        runner.finished.connect(lambda ok: self._on_done("guixin", ok))
        runner.sn_done.connect(lambda ok: self._on_done("sinan", ok))
        runner.zg_done.connect(lambda ok: self._on_done("zhan_gong", ok))
        runner.trade_done.connect(lambda ok: self._on_done("trade", ok))

        runner.zg_progress.connect(self._on_progress)
        runner.sn_progress.connect(self._on_progress)
        runner.trade_progress.connect(self._on_progress)

    @property
    def running(self) -> bool:
        return self._running

    def start(self, keys: list[str], params_fn=None) -> bool:
        """启动批量执行。keys 为任务 key 列表，按顺序执行。"""
        if self._running:
            return False
        if not keys:
            return False
        self._keys = list(keys)
        self._params_fn = params_fn
        self._index = 0
        self._running = True
        self._stop = False
        self._wait_done = set()
        self._started_at = time.monotonic()
        self.batch_started.emit()
        self._run_next()
        return True

    def stop(self) -> None:
        """请求停止当前任务并终止批量执行。"""
        if not self._running:
            return
        self._stop = True
        if self._runner.running:
            self._runner.stop()

    # ---------------- 内部 ----------------

    def _run_next(self) -> None:
        if self._stop or self._index >= len(self._keys):
            ok = not self._stop
            self._running = False
            if self._started_at is not None:
                secs = time.monotonic() - self._started_at
                self._started_at = None
                self.log.emit(
                    f"本次批量执行共用时 {self._fmt_elapsed(secs)}")
            self.batch_finished.emit(ok)
            return
        key = self._keys[self._index]
        self._wait_done = {key}
        name = TASK_NAMES.get(key, key)
        self.log.emit("=" * 40)
        self.log.emit(f"开始任务：{name}")
        self.task_started.emit(key)
        try:
            params = self._params_fn(key) if self._params_fn else {}
            self._start(key, params or {})
        except Exception as e:  # noqa: BLE001
            self.log.emit(f"任务启动失败：{e}")
            self._on_done(key, False)

    def _start(self, key: str, params: dict) -> None:
        r = self._runner
        if key == "guixin":
            r.start("guixin_start")
        elif key == "sinan":
            r.start_sinan(params)
        elif key == "zhan_gong":
            r.start_zhan_gong(params)
        elif key == "trade":
            r.start_trade(params)
        else:
            raise ValueError(f"未知任务: {key}")

    def _on_done(self, key: str, ok: bool) -> None:
        if key not in self._wait_done:
            return
        self._wait_done.clear()
        name = TASK_NAMES.get(key, key)
        if ok:
            self.log.emit(f"任务成功：{name}")
        else:
            self.log.emit(f"任务失败/已停止：{name}")
        self.task_finished.emit(key, ok)
        self._index += 1
        self._run_next()

    def _on_progress(self, msg: str) -> None:
        if self._index < 0 or self._index >= len(self._keys):
            return
        key = self._keys[self._index]
        name = TASK_NAMES.get(key, key)
        self.log.emit(msg)

    @staticmethod
    def _fmt_elapsed(secs: float) -> str:
        """把秒格式化为 H 小时 M 分 S 秒。"""
        secs = int(round(secs))
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h} 小时 {m} 分 {s} 秒"
        if m:
            return f"{m} 分 {s} 秒"
        return f"{s} 秒"