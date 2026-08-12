"""MAA 控制器封装：连接模拟器、截图、点击、加载资源、执行任务。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PIL import Image

from maa.controller import AdbController
from maa.event_sink import EventSink
from maa.resource import Resource
from maa.tasker import Tasker, TaskerEventSink
from maa.toolkit import Toolkit

logger = logging.getLogger("sangui.controller")

# 可选识别/输入方法组合（默认值即可，性能足够）
DEFAULT_SCREENCAP = -57  # MaaAdbScreencapMethodEnum.Default
DEFAULT_INPUT = -9  # MaaAdbInputMethodEnum.Default


class MaaController:
    """封装 MAA 连接与任务执行。"""

    def __init__(self):
        self._controller: Optional[AdbController] = None
        self._resource: Resource = Resource()
        self._tasker: Optional[Tasker] = None
        self._connected = False
        self._user_path = Path(".").resolve() / "maa_user"

    def init(self) -> None:
        """初始化 MAA 运行环境（仅需一次）。"""
        Toolkit.init_option(str(self._user_path))
        logger.info("Toolkit initialized. user_path=%s", self._user_path)

    def connect(
        self,
        adb_path: str,
        address: str,
        screencap_methods: int = DEFAULT_SCREENCAP,
        input_methods: int = DEFAULT_INPUT,
    ) -> bool:
        """连接模拟器。"""
        self._controller = AdbController(
            adb_path=adb_path,
            address=address,
            screencap_methods=screencap_methods,
            input_methods=input_methods,
        )
        self._controller.post_connection().wait()
        self._connected = True
        logger.info("Controller connected: %s", address)
        self._rebind_tasker()
        return True

    def _rebind_tasker(self) -> None:
        """重新绑定 tasker（资源变化后调用）。"""
        if not self._connected:
            return
        self._tasker = Tasker()
        self._tasker.bind(self._resource, self._controller)
        try:
            from maa.define import LoggingLevelEnum
            self._tasker.set_stdout_level(LoggingLevelEnum.Error)
        except:
            pass
        logger.debug("Tasker rebound.")

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def controller(self) -> Optional[AdbController]:
        return self._controller

    def load_resource(self, resource_path: str) -> bool:
        """加载资源包（pipeline + 模板图 + OCR）。"""
        self._resource.post_bundle(resource_path).wait()
        logger.info("Resource loaded: %s", resource_path)
        self._rebind_tasker()
        return True

    def screencap(self) -> Image.Image:
        """截取当前屏幕，返回 PIL Image。"""
        if not self._controller:
            raise RuntimeError("Controller not connected.")
        arr = self._controller.post_screencap().wait().get()
        # MAA 返回 BGR numpy.ndarray (H,W,3)
        return Image.fromarray(np.asarray(arr)[:, :, ::-1], "RGB")

    def click(self, x: int, y: int) -> None:
        """模拟点击。"""
        if not self._controller:
            raise RuntimeError("Controller not connected.")
        self._controller.post_click(x, y).wait()

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 500) -> None:
        """模拟滑动。"""
        if not self._controller:
            raise RuntimeError("Controller not connected.")
        self._controller.post_swipe(x1, y1, x2, y2, duration_ms).wait()

    def run_task(
        self,
        task_name: str,
        callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """执行指定的 pipeline 任务（阻塞）。"""
        if not self._tasker:
            raise RuntimeError("Tasker not initialized.")

        if callback is not None:
            self._tasker.add_sink(_TaskerEventSinkImpl(callback))

        result = self._tasker.post_task(task_name).wait().get()
        logger.info("Task %s finished. success=%s", task_name, result)
        return bool(result)

    def stop(self) -> None:
        """停止当前任务。"""
        if self._tasker:
            self._tasker.post_stop().wait()

    def recognize(self, template: str, threshold: float = 0.8) -> list:
        """用模板匹配识别当前屏幕，返回命中框列表。

        template 为相对资源目录的模板名（如 "guixin_entry.png"）。
        返回 [(x, y, w, h, score), ...]。
        """
        if not self._tasker:
            raise RuntimeError("Tasker not initialized.")
        from maa.pipeline import JRecognitionType, JTemplateMatch
        arr = self._controller.post_screencap().wait().get()
        job = self._tasker.post_recognition(
            JRecognitionType.TemplateMatch,
            JTemplateMatch([template], threshold=[threshold]),
            arr,
        )
        detail = job.wait().get() or {}
        boxes = []
        for d in detail.get("filtered", []) or []:
            box = d.get("box") or {}
            boxes.append(
                (box.get("x", 0), box.get("y", 0),
                 box.get("w", 0), box.get("h", 0),
                 d.get("score", 0.0))
            )
        return boxes

    def disconnect(self) -> None:
        """断开连接。"""
        if self._tasker:
            self._tasker.post_stop().wait()
        self._controller = None
        self._tasker = None
        self._connected = False


# 高频/无意义的 MAA 通知：直接忽略，避免刷屏
_NOISY_NOTIFICATIONS = {
    "Click", "Swipe", "Screencap", "ScreencapWithCache", "ReadyToExecute",
    "Parsed", "ResourceUpdated", "DoNothing", "Wait", "Sleep",
}


class _TaskerEventSinkImpl(TaskerEventSink):
    """把 MAA Tasker 事件日志转发到 callback（已过滤冗余通知）。"""

    def __init__(self, callback: Callable[[str], None]):
        super().__init__()
        self._callback = callback

    def on_raw_notification(self, tasker, msg: str, details: dict) -> None:
        name = msg.split(":", 1)[0].strip().strip('"')
        if name in _NOISY_NOTIFICATIONS:
            return
        detail = details.get("detail", "") if isinstance(details, dict) else ""
        self._callback(f"[{name}] {detail}")

    def on_unknown_notification(self, instance, msg: str, details: dict) -> None:
        self._callback(f"[UNKNOWN:{msg}] {details}")