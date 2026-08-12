"""任务运行器：在单一后台线程内完成 controller 生命周期 + 任务执行。

MAA 的 AdbController / Tasker 绑定到创建它的线程，跨线程调用 post_* 会卡死。
因此本类自建 controller，init->connect->load->run_task 全程在同一线程内完成，
GUI 主线程只通过信号接收结果，杜绝跨线程访问导致的假死。
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from app.core import config
from app.core.maa_controller import MaaController

logger = logging.getLogger("sangui.runner")


class TaskRunner(QObject):
    """封装后台线程内的 controller 生命周期与任务执行。

    全局共享单例：同一时刻仅允许执行一个任务（归心/司南/配将互斥）。
    """

    status = pyqtSignal(bool, str)  # connected, message
    log = pyqtSignal(str)
    finished = pyqtSignal(bool)
    task_started = pyqtSignal(str)  # task name
    recognition = pyqtSignal(str)  # 调试识别结果文本

    def __init__(
        self,
        adb_path: str | None = None,
        address: str | None = None,
        resource_path: str | None = None,
    ):
        super().__init__()
        params = config.get_connection_params()
        self._adb_path = adb_path or params["adb_path"]
        self._address = address or params["address"]
        self._resource_path = resource_path or params["resource_path"]
        self._controller: Optional[MaaController] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_requested = False
        self._connecting = False

    @property
    def running(self) -> bool:
        return self._running

    def connect_async(self) -> None:
        """在后台线程建立连接并加载资源（single-shot，不执行任务）。"""
        if self._running:
            logger.warning("Cannot connect while a task is running.")
            return
        if self._connecting:
            logger.warning("Connection already in progress.")
            return
        if self._thread and self._thread.is_alive():
            logger.warning("Thread already alive.")
            return
        self._connecting = True
        self._thread = threading.Thread(target=self._connect_blocking, daemon=True)
        self._thread.start()

    def reconnect(
        self,
        adb_path: str,
        address: str,
        resource_path: str,
    ) -> None:
        """按新参数断开旧连接并重新连接（设置页保存后调用）。"""
        if self._running or self._connecting:
            logger.warning("Cannot reconnect while busy.")
            return
        self._adb_path = adb_path
        self._address = address
        self._resource_path = resource_path
        self._controller = None
        self.status.emit(False, "重新连接中...")
        self.connect_async()

    def _connect_blocking(self) -> None:
        try:
            ctrl = MaaController()
            ctrl.init()
            ctrl.connect(self._adb_path, self._address)
            ctrl.load_resource(self._resource_path)
            self._controller = ctrl
            self.status.emit(True, "连接成功")
        except Exception as e:  # noqa: BLE001
            logger.exception("Connect failed")
            self.status.emit(False, str(e))
        finally:
            self._connecting = False

    def start(self, task_name: str) -> None:
        """在后台线程启动任务（复用已建立的 controller / 线程）。

        互斥：已有任务在跑或正在连接时不启动，保证同一时刻只执行一个任务。
        """
        if self._running:
            logger.warning("Task already running.")
            return
        if self._connecting:
            logger.warning("Connecting in progress, task not started.")
            return
        if self._controller is None:
            logger.warning("Controller not connected.")
            return
        self._running = True
        self._stop_requested = False
        self.task_started.emit(task_name)
        t = threading.Thread(target=self._run, args=(task_name,), daemon=True)
        t.start()

    def _run(self, task_name: str) -> None:
        success = False
        try:
            self.log.emit(f"开始任务: {task_name}")
            success = self._controller.run_task(
                task_name,
                callback=lambda msg: self.log.emit(msg),
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("Task failed")
            self.log.emit(f"任务异常: {e}")
        finally:
            self._running = False
            self.finished.emit(success)

    def stop(self) -> None:
        """请求停止当前任务（非阻塞）。"""
        if not self._running:
            return
        self._stop_requested = True
        t = threading.Thread(target=self._do_stop, daemon=True)
        t.start()
        logger.info("Stop requested.")

    def _do_stop(self) -> None:
        try:
            if self._controller:
                self._controller.stop()
        except Exception:  # noqa: BLE001
            logger.exception("Stop failed")

    def disconnect(self) -> None:
        """断开连接（在绑定线程内执行）。"""
        if self._controller:
            ctrl = self._controller
            self._controller = None
            t = threading.Thread(target=ctrl.disconnect, daemon=True)
            t.start()

    def recognize_async(self, template: str, threshold: float = 0.8) -> None:
        """在后台线程对指定模板做模板匹配识别，结果经 recognition 信号返回。"""
        if self._controller is None:
            self.recognition.emit("未连接，无法识别")
            return
        if self._running or self._connecting:
            self.recognition.emit("任务执行中，无法识别")
            return
        ctrl = self._controller
        t = threading.Thread(
            target=self._do_recognize,
            args=(ctrl, template, threshold),
            daemon=True,
        )
        t.start()

    def _do_recognize(self, ctrl, template: str, threshold: float) -> None:
        try:
            boxes = ctrl.recognize(template, threshold)
            if not boxes:
                self.recognition.emit(f"未命中: {template}")
                return
            parts = [f"命中 {len(boxes)} 处:"]
            for x, y, w, h, score in boxes:
                parts.append(f"  ({x},{y}) {w}x{h} score={score:.2f}")
            self.recognition.emit("\n".join(parts))
        except Exception as e:  # noqa: BLE001
            logger.exception("Recognition failed")
            self.recognition.emit(f"识别失败: {e}")