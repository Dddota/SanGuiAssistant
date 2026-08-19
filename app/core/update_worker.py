"""更新操作的后台 Worker：在线程中调用 updater，结果经 Qt 信号回主线程。

避免 check / apply 阻塞 GUI。QObject 信号跨线程是安全的，emit 即可。
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from app.core import updater

logger = logging.getLogger("sangui.updater")


class UpdateWorker(QObject):
    """封装后台检查与应用的 Worker。

    用法：
        worker = UpdateWorker()
        worker.check_done.connect(on_check_done)
        worker.check_error.connect(on_check_error)
        worker.apply_done.connect(on_apply_done)
        worker.check()
    调用方需持有 worker 引用（如挂在窗口/按钮属性上）防止被 GC。
    """

    check_done = pyqtSignal(dict)       # 最新版信息；无更新为 None 或 {}（由连接端判断）
    check_error = pyqtSignal(str)       # 检查过程异常（一般不期望触发）
    apply_progress = pyqtSignal(str)    # 应用更新过程进度提示
    apply_done = pyqtSignal(bool, str)  # (成功与否, 消息)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._busy = False  # 幂等：忙时忽略重复的 check / apply

    def check(self) -> None:
        """后台检查是否有更新。结果经 check_done / check_error 返回。"""
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._check_thread, daemon=True).start()

    def _check_thread(self) -> None:
        try:
            info = updater.check_for_update()
        except Exception as e:  # noqa: BLE001
            logger.warning("check worker raised: %s", e)
            self.check_error.emit(str(e))
        else:
            self.check_done.emit(info or {})
        finally:
            self._busy = False

    def apply(self, info: dict) -> None:
        """后台下载并应用更新。结果经 apply_progress / apply_done 返回。"""
        if self._busy:
            return
        self._busy = True
        threading.Thread(
            target=self._apply_thread, args=(info,), daemon=True
        ).start()

    def _apply_thread(self, info: dict) -> None:
        try:
            updater.apply_update(
                info, on_progress=self.apply_progress.emit
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("apply worker raised: %s", e)
            self.apply_done.emit(False, str(e))
        else:
            self.apply_done.emit(True, "更新脚本已启动，程序即将退出")
        finally:
            self._busy = False