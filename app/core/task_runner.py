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
    ocr_result = pyqtSignal(list)  # OCR 识别结果列表
    scan_result = pyqtSignal(dict)  # 全量扫描增量结果 {"found": [...], "done": bool, "stale": int}
    scan_finished = pyqtSignal(bool)  # 全量扫描结束
    hero_scan_progress = pyqtSignal(str)  # 详情扫描日志
    hero_scan_hero = pyqtSignal(object)   # 每识别一名 UserHero
    hero_scan_done = pyqtSignal(list)     # 全部完成，返回 UserHero 列表
    zg_progress = pyqtSignal(str)    # 战功引擎日志
    zg_done = pyqtSignal(bool)       # 战功引擎结束
    zg_teams = pyqtSignal(list)      # 战功：读取到的玩家队伍列表
    sn_progress = pyqtSignal(str)    # 司南引擎日志
    sn_done = pyqtSignal(bool)       # 司南引擎结束
    trade_progress = pyqtSignal(str)  # 辅助交易引擎日志
    trade_done = pyqtSignal(bool)     # 辅助交易引擎结束
    trade_result = pyqtSignal(list)   # 辅助交易：扫描结果列表

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

    # ---------------- 战功自动攻城 ----------------

    def start_zhan_gong(self, params: dict | None = None) -> None:
        """在后台线程启动战功自动攻城引擎。"""
        if self._controller is None:
            self.zg_done.emit(False)
            return
        if self._running or self._connecting:
            self.zg_done.emit(False)
            return
        self._running = True
        self._stop_requested = False
        ctrl = self._controller
        self.task_started.emit("zhan_gong")
        t = threading.Thread(
            target=self._do_zhan_gong,
            args=(ctrl, params or {}),
            daemon=True,
        )
        t.start()

    def _do_zhan_gong(self, ctrl, params: dict) -> None:
        try:
            from app.core.zhan_gong_engine import ZhanGongEngine
            engine = ZhanGongEngine(ctrl, params)

            def _on_progress(msg: str) -> None:
                self.zg_progress.emit(msg)

            def _should_stop() -> bool:
                return self._stop_requested

            report = engine.run(
                on_progress=_on_progress,
                should_stop=_should_stop,
            )
            try:
                report_path = engine.save_report()
                self.zg_progress.emit(f"报告已保存：{report_path}")
            except Exception as re:  # noqa: BLE001
                logger.warning("Save zhan_gong report failed: %s", re)
            self.zg_progress.emit(
                f"战功刷取结束：共攻打 {report.get('total_attacks', 0)} 次")
            self.zg_done.emit(True)
        except Exception as e:  # noqa: BLE001
            logger.exception("ZhanGong failed")
            self.zg_progress.emit(f"战功任务异常：{e}")
            self.zg_done.emit(False)
        finally:
            self._running = False

    # ---------------- 自动司南 ----------------

    def start_sinan(self, params: dict | None = None) -> None:
        """在后台线程启动自动司南引擎。"""
        if self._controller is None:
            self.sn_done.emit(False)
            return
        if self._running or self._connecting:
            self.sn_done.emit(False)
            return
        self._running = True
        self._stop_requested = False
        ctrl = self._controller
        self.task_started.emit("sinan")
        t = threading.Thread(
            target=self._do_sinan,
            args=(ctrl, params or {}),
            daemon=True,
        )
        t.start()

    def _do_sinan(self, ctrl, params: dict) -> None:
        try:
            from app.core.sinan_engine import SinanEngine
            engine = SinanEngine(ctrl, params)

            def _on_progress(msg: str) -> None:
                self.sn_progress.emit(msg)

            def _should_stop() -> bool:
                return self._stop_requested

            report = engine.run(
                on_progress=_on_progress,
                should_stop=_should_stop,
            )
            # 连续多次未收货宝箱判定失败 → 交给 BatchRunner 标记失败并进入下一个
            ok = not bool(report.get("failed"))
            self.sn_done.emit(ok)
        except Exception as e:  # noqa: BLE001
            logger.exception("Sinan failed")
            self.sn_progress.emit(f"司南任务异常：{e}")
            self.sn_done.emit(False)
        finally:
            self._running = False

    def read_my_teams_async(self) -> None:
        """在后台线程读取大地图右侧玩家队伍列表，结果经 zg_teams 信号返回。"""
        if self._controller is None:
            self.zg_teams.emit([])
            return
        if self._running or self._connecting:
            self.zg_teams.emit([])
            return
        ctrl = self._controller
        t = threading.Thread(
            target=self._do_read_my_teams,
            args=(ctrl,),
            daemon=True,
        )
        t.start()

    def _do_read_my_teams(self, ctrl) -> None:
        try:
            from app.core.zhan_gong_engine import ZhanGongEngine
            engine = ZhanGongEngine(ctrl, {})
            teams = engine.read_my_teams()
            self.zg_teams.emit(teams)
        except Exception as e:  # noqa: BLE001
            logger.exception("Read my teams failed")
            self.zg_teams.emit([])

    # ---------------- 辅助交易 ----------------

    def start_trade(self, params: dict | None = None) -> None:
        """在后台线程启动辅助交易扫描引擎。"""
        if self._controller is None:
            self.trade_done.emit(False)
            return
        if self._running or self._connecting:
            self.trade_done.emit(False)
            return
        self._running = True
        self._stop_requested = False
        ctrl = self._controller
        self.task_started.emit("trade")
        t = threading.Thread(
            target=self._do_trade,
            args=(ctrl, params or {}),
            daemon=True,
        )
        t.start()

    def _do_trade(self, ctrl, params: dict) -> None:
        try:
            from app.core.trade_engine import TradeEngine
            engine = TradeEngine(ctrl, params)

            def _on_progress(msg: str) -> None:
                self.trade_progress.emit(msg)

            def _should_stop() -> bool:
                return self._stop_requested

            report = engine.run(
                on_progress=_on_progress,
                should_stop=_should_stop,
            )
            try:
                report_path = engine.save_report()
                self.trade_progress.emit(f"报告已保存：{report_path}")
            except Exception as re:  # noqa: BLE001
                logger.warning("Save trade report failed: %s", re)
            self.trade_result.emit(report.get("items", []))
            self.trade_progress.emit(
                f"辅助交易扫描结束：共 {report.get('total', 0)} 个关注物品")
            self.trade_done.emit(True)
        except Exception as e:  # noqa: BLE001
            logger.exception("Trade failed")
            self.trade_progress.emit(f"辅助交易任务异常：{e}")
            self.trade_done.emit(False)
        finally:
            self._running = False

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

    def ocr_async(
        self,
        roi: tuple[int, int, int, int] | None = None,
        expected: list[str] | None = None,
    ) -> None:
        """在后台线程对当前屏幕做 OCR，结果经 ocr_result 信号返回。"""
        if self._controller is None:
            self.ocr_result.emit([])
            return
        if self._running or self._connecting:
            self.ocr_result.emit([])
            return
        ctrl = self._controller
        t = threading.Thread(
            target=self._do_ocr,
            args=(ctrl, roi, expected),
            daemon=True,
        )
        t.start()

    def _do_ocr(self, ctrl, roi, expected) -> None:
        try:
            results = ctrl.ocr(roi, expected)
            self.ocr_result.emit(results)
        except Exception as e:  # noqa: BLE001
            logger.exception("OCR failed")
            self.ocr_result.emit([{"error": str(e)}])

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

    # ---------------- 详情扫描（逐一点头像读详情） ----------------

    def scan_hero_details(self, params: dict | None = None) -> None:
        """详情扫描：点左侧头像 → 读右侧详情 → 翻页，直到扫完全部武将。

        结果通过 hero_scan_progress（日志）/ hero_scan_hero（每武将增量）/
        hero_scan_done（全部完成） 信号返回。
        """
        if self._controller is None:
            self.hero_scan_done.emit([])
            return
        if self._running or self._connecting:
            self.hero_scan_done.emit([])
            return
        self._running = True
        self._stop_requested = False
        ctrl = self._controller
        t = threading.Thread(
            target=self._do_hero_scan,
            args=(ctrl, params or {}),
            daemon=True,
        )
        t.start()

    def _do_hero_scan(self, ctrl, params: dict) -> None:
        try:
            from app.core.hero_scanner import HeroScanner
            from app.data.hero_lib import get_library
            lib = get_library()
            scanner = HeroScanner(ctrl, lib, params)

            def _on_progress(msg: str) -> None:
                self.hero_scan_progress.emit(msg)

            def _on_hero(hero) -> None:
                self.hero_scan_hero.emit(hero)

            def _should_stop() -> bool:
                return self._stop_requested

            results = scanner.scan_all(
                on_progress=_on_progress,
                on_hero=_on_hero,
                should_stop=_should_stop,
            )
            # 保存诊断报告
            try:
                report_path = scanner.save_report()
                self.hero_scan_progress.emit(f"报告已保存：{report_path}")
            except Exception as re:
                logger.warning("Save scan report failed: %s", re)
            self.hero_scan_done.emit(results)
        except Exception as e:  # noqa: BLE001
            logger.exception("Hero detail scan failed")
            self.hero_scan_progress.emit(f"扫描异常：{e}")
            self.hero_scan_done.emit([])
        finally:
            self._running = False

    def scan_user_heroes(
        self,
        roi: tuple[int, int, int, int] | None = None,
        scroll_params: dict | None = None,
    ) -> None:
        """在后台线程自动滚动识别用户全部武将。

        流程：整屏 OCR -> 提取武将名+等级 -> swipe 上滑 -> 再 OCR 去重，
        连续 N 屏无新增判定到底。结果经 scan_result 增量返回。
        """
        if self._controller is None:
            self.scan_finished.emit(False)
            return
        if self._running or self._connecting:
            self.scan_finished.emit(False)
            return
        p = scroll_params or {}
        self._running = True
        self._stop_requested = False
        ctrl = self._controller
        t = threading.Thread(
            target=self._do_scan,
            args=(ctrl, roi, p),
            daemon=True,
        )
        t.start()

    def _do_scan(self, ctrl, roi, p: dict) -> None:
        sx = p.get("swipe_x", 540)
        sy1 = p.get("swipe_y1", 700)
        sy2 = p.get("swipe_y2", 200)
        duration = p.get("duration_ms", 300)
        max_stale = p.get("max_stale", 3)
        try:
            seen: set = set()
            stale = 0
            while stale < max_stale:
                if self._stop_requested:
                    break
                results = ctrl.ocr(roi, None)
                # 本屏全部条目（text+box），交由 UI 层解析武将名与等级
                frame = [
                    {
                        "text": r.get("text", "").strip(),
                        "box": r.get("box", (0, 0, 0, 0)),
                    }
                    for r in results if r.get("text", "").strip()
                ]
                new_items = [
                    it for it in frame if it["text"] not in seen
                ]
                seen.update(it["text"] for it in frame)
                self.scan_result.emit({
                    "frame": frame,
                    "found": new_items,
                    "done": False,
                    "stale": stale,
                })
                if not new_items:
                    stale += 1
                else:
                    stale = 0
                if stale >= max_stale:
                    break
                ctrl.swipe(sx, sy1, sx, sy2, duration)
                import time
                time.sleep(0.4)
            self.scan_result.emit({"frame": [], "found": [], "done": True, "stale": stale})
        except Exception as e:  # noqa: BLE001
            logger.exception("Scan failed")
            self.scan_result.emit({"found": [], "done": True, "stale": 0, "error": str(e)})
        finally:
            self._running = False
            self.scan_finished.emit(True)