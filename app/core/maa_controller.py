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

from app.core.config import app_root as _app_root

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
        self._user_path = _app_root() / "maa_user"

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
        """连接模拟器。

        MAA 的 post_connection().wait() 只等动作结束，不保证连接成功
        （adb 失败仅写入 maafw.log）。连接失败必须抛异常，让上层知道
        并停止流程，避免假连接让 UI 显示"已连接"。
        """
        if not adb_path or not Path(adb_path).is_file():
            raise ConnectionError(
                f"adb 不存在: {adb_path!r}，请检查配置或选择有效的模拟器")

        self._controller = AdbController(
            adb_path=adb_path,
            address=address,
            screencap_methods=screencap_methods,
            input_methods=input_methods,
        )
        self._controller.post_connection().wait()
        if not self._controller.connected:
            self._controller = None
            self._connected = False
            raise ConnectionError(
                f"无法连接模拟器 {address}（adb: {adb_path}）。"
                "请确认模拟器已启动、ADB 路径正确，并已开启 ADB 调试。")
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
        """加载资源包（pipeline + 模板图 + OCR 模型）。

        OCR 模型目录（可选）：{resource_path}/model/，含 det.onnx / rec.onnx / keys.txt。
        若存在则一并加载，否则 OCR 识别不可用（点识别将失败）。
        """
        self._resource.post_bundle(resource_path).wait()
        logger.info("Resource loaded: %s", resource_path)
        # 可选 OCR 模型（MAA 标准：{resource}/model/ocr/ 含 det.onnx/rec.onnx/keys.txt）
        model_ocr = Path(resource_path) / "model" / "ocr"
        if model_ocr.is_dir():
            self._resource.post_ocr_model(str(model_ocr)).wait()
            logger.info("OCR model loaded: %s", model_ocr)
        else:
            logger.warning("OCR model dir not found: %s", model_ocr)
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
        """执行指定的 pipeline 任务（阻塞）。

        若提供 callback，会临时开启 MAA 调试模式：让所有识别节点（含非 focus）
        都产生识别回调，从而把模板命中/分数上报给日志，便于排查
        「模板因背景色不一致匹配失败 → 点不到按钮」的问题。
        任务结束后恢复原调试模式。
        """
        if not self._tasker:
            raise RuntimeError("Tasker not initialized.")

        prev_debug = False
        if callback is not None:
            self._tasker.add_sink(_TaskerEventSinkImpl(callback))
            try:
                prev_debug = bool(Tasker.set_debug_mode(True))
            except Exception:  # noqa: BLE001
                prev_debug = False

        try:
            result = self._tasker.post_task(task_name).wait().get()
        finally:
            if callback is not None:
                try:
                    Tasker.set_debug_mode(prev_debug)
                except Exception:  # noqa: BLE001
                    pass
        logger.info("Task %s finished. success=%s", task_name, result)
        return bool(result)

    def input_text(self, text: str) -> None:
        """模拟文本输入（用于搜索框等）。"""
        if not self._controller:
            raise RuntimeError("Controller not connected.")
        self._controller.post_input_text(text).wait()

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
        detail = job.wait().get()
        if not detail:
            return []
        boxes = []
        for node in detail.nodes:
            reco = getattr(node, "recognition", None)
            for d in (getattr(reco, "filtered_results", None) or []):
                box = d.box if isinstance(d.box, (list, tuple)) else (d.box.x, d.box.y, d.box.w, d.box.h)
                boxes.append(
                    (box[0], box[1], box[2], box[3], getattr(d, "score", 0.0))
                )
        return boxes

    def ocr(
        self,
        roi: tuple[int, int, int, int] | None = None,
        expected: list[str] | None = None,
    ) -> list[dict]:
        """对当前屏幕做 OCR，返回识别结果列表。

        roi 为 (x, y, w, h)；None 表示整屏。
        expected 为期望文本列表（模糊匹配）；None 表示识别全部文本。
        返回 [{"text": str, "box": (x,y,w,h), "score": float}, ...]。
        """
        if not self._controller or not self._tasker:
            raise RuntimeError("Controller/Tasker not initialized.")
        from maa.pipeline import JOCR, JRecognitionType
        roi_val = roi if roi else (0, 0, 0, 0)
        exp = expected if expected else []
        job = self._tasker.post_recognition(
            JRecognitionType.OCR,
            JOCR(
                expected=exp,
                roi=roi_val,
                threshold=0.3,
            ),
            self._controller.post_screencap().wait().get(),
        )
        detail = job.wait().get()
        if not detail:
            return []
        results = []
        for node in detail.nodes:
            reco = getattr(node, "recognition", None)
            for d in (getattr(reco, "filtered_results", None) or []):
                box = d.box if isinstance(d.box, (list, tuple)) else (d.box.x, d.box.y, d.box.w, d.box.h)
                results.append({
                    "text": getattr(d, "text", ""),
                    "box": (box[0], box[1], box[2], box[3]),
                    "score": getattr(d, "score", 0.0),
                })
        return results

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
    """把 MAA Tasker 事件日志转发到 callback（已过滤冗余通知）。

    模板匹配（TemplateMatch）节点额外上报命中/未命中与最高分，
    便于排查因背景色/模板不一致导致『点不到按钮』的问题。
    """

    def __init__(self, callback: Callable[[str], None]):
        super().__init__()
        self._callback = callback

    def _log_recognition(self, tasker, details: dict) -> None:
        """上报一次识别结果（带命中与分数）。"""
        reco_id = details.get("reco_id")
        if reco_id is None:
            return
        try:
            det = tasker.get_recognition_detail(int(reco_id))
        except Exception as e:  # noqa: BLE001
            self._callback(f"[识别] 读取识别详情失败: {e}")
            return
        if not det:
            return
        node = details.get("name") or det.name
        if det.algorithm == "TemplateMatch":
            scores = []
            for r in det.all_results:
                if hasattr(r, "score"):
                    scores.append(float(r.score))
            best = max(scores) if scores else 0.0
            if det.hit:
                box = det.box
                self._callback(
                    f"[识别] {node} 命中 ({box.x},{box.y}) score={best:.2f}")
            else:
                self._callback(
                    f"[识别][失败] {node} 未命中，最高score={best:.2f}"
                    f"（可能背景色/模板不一致导致点不到按钮）")
        else:
            self._callback(f"[识别] {node} alg={det.algorithm} hit={det.hit}")

    def on_raw_notification(self, tasker, msg: str, details: dict) -> None:
        name = msg.split(":", 1)[0].strip().strip('"')
        if name in _NOISY_NOTIFICATIONS:
            return
        if name.startswith("Node.Recognition") and isinstance(details, dict):
            self._log_recognition(tasker, details)
            return
        detail = details.get("detail", "") if isinstance(details, dict) else ""
        self._callback(f"[{name}] {detail}")

    def on_unknown_notification(self, instance, msg: str, details: dict) -> None:
        self._callback(f"[UNKNOWN:{msg}] {details}")