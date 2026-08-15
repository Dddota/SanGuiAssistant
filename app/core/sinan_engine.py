"""自动司南引擎（轻量）。

复用 MaaController.recognize / click 逐节点识别并点击，每个识别步骤都
通过 on_progress 主动上报命中/未命中 + 分数，便于排查『模板因背景色
不一致匹配失败 → 点不到按钮』的问题。

流程与 app/assets/pipeline/sinan.json 保持一致：
1. 点司南页签按钮(sinan_tab_btn)
2. 等司南面板出现(sinan_first_item)
3. 使用第一个司南(sinan_first_item) → 触发宝箱/村庄事件
4. 循环处理：宝箱(sinan_chest) / 村庄弹窗(sinan_village_popup) / 确认按钮(sinan_village_confirm_btn)
5. 识别不可用百分比(sinan_unavailable_percent) → 结束
6. 关奖励弹窗，回到第 3 步
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

logger = logging.getLogger("sangui.sinan")


class SinanEngine:
    """自动司南引擎（纯逻辑，controller 由 TaskRunner 同线程调用）。"""

    THRESHOLD = 0.7
    # 无量最多使用次数（防失控）
    MAX_USES = 50

    def __init__(self, ctrl, params: Optional[dict] = None):
        self.ctrl = ctrl
        p = params or {}
        self.threshold: float = p.get("threshold", self.THRESHOLD)
        self.max_uses: int = p.get("max_uses", self.MAX_USES)
        # 识别多久算失败（s）
        self.timeout: float = p.get("timeout", 3.0)
        # 点击后的等待（s）
        self.wait_after: float = p.get("wait_after", 1.5)
        self.report: dict = {
            "uses": 0,
            "chests": 0,
            "villages": 0,
            "unavailable": False,
            "finished_at": "",
        }

    # ---------------- 工具 ----------------

    def _log(self, on_progress, msg: str) -> None:
        if on_progress:
            on_progress(msg)
        logger.info(msg)

    def _sleep(self, seconds: float, should_stop=None) -> bool:
        """可中断睡眠。返回 True 表示被要求停止。"""
        end = time.time() + seconds
        while time.time() < end:
            if should_stop and should_stop():
                return True
            time.sleep(0.05)
        return False

    def _find(self, template: str, desc: str, on_progress=None) -> Optional[dict]:
        """识别一个模板，返回 dict{cx,cy,x,y,w,h,score} 或 None。带命中/未命中日志。"""
        try:
            boxes = self.ctrl.recognize(template, self.threshold)
        except Exception as e:  # noqa: BLE001
            self._log(on_progress, f"[识别][异常] {desc}（{template}）: {e}")
            return None
        if boxes:
            x, y, w, h, s = boxes[0]
            s = float(s)
            cx = x + w // 2
            cy = y + h // 2
            self._log(on_progress,
                      f"[识别] {desc} 命中 ({x},{y}) score={s:.2f}")
            return {"cx": cx, "cy": cy, "x": x, "y": y,
                    "w": w, "h": h, "score": s}
        self._log(on_progress,
                  f"[识别][失败] {desc} 未命中，最高score=0.00"
                  f"（可能背景色/模板不一致导致点不到按钮）")
        return None

    def _wait_find(self, template: str, desc: str, on_progress=None,
                   should_stop=None) -> Optional[dict]:
        """在超时内反复识别，直到命中或超时。返回命中 dict 或 None。"""
        end = time.time() + self.timeout
        while time.time() < end:
            if should_stop and should_stop():
                return None
            r = self._find(template, desc, on_progress)
            if r:
                return r
            if self._sleep(0.5, should_stop):
                return None
        self._log(on_progress, f"[识别][失败] {desc} 超时未命中")
        return None

    def _click(self, x: int, y: int, desc: str, on_progress=None) -> None:
        self.ctrl.click(x, y)
        self._log(on_progress, f"[点击] {desc} ({x},{y})")

    # ---------------- 主流程 ----------------

    def run(
        self,
        on_progress: Optional[Callable[[str], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> dict:
        """执行一次自动司南，返回统计报告。"""
        self._log(on_progress, "开始司南任务：打开司南面板")

        # 1. 打开司南面板（点司南页签按钮）
        tab = self._wait_find("sinan_tab_btn.png", "司南页签按钮",
                              on_progress, should_stop)
        if not tab:
            self._log(on_progress, "错误：未找到司南页签按钮，终止")
            self.report["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            return self.report
        self._click(tab["cx"], tab["cy"], "司南页签按钮", on_progress)
        if self._sleep(2.0, should_stop):
            return self._finish(on_progress)

        # 2. 等司南面板出现（第一个司南物品）
        first = self._wait_find("sinan_first_item.png", "司南面板（可用司南）",
                                on_progress, should_stop)
        if not first:
            self._log(on_progress, "错误：司南面板未出现，终止")
            return self._finish(on_progress)

        # 3. 循环使用司南
        uses = 0
        while uses < self.max_uses:
            if should_stop and should_stop():
                break

            # 3.1 使用当前第一个司南（点下半部分紫色司南图标，而非整个item中心）
            item = self._find("sinan_first_item.png", "可用司南",
                              on_progress)
            if not item:
                # 没有可用司南了 → 检查是否不可用百分比 → 结束
                self._log(on_progress, "未找到可用司南，检查剩余情况")
                break
            # 点击司南图标（模板下半部分紫色菱形）
            click_x = item["cx"]
            click_y = item["y"] + item["h"] * 3 // 4
            self._click(click_x, click_y, "使用司南", on_progress)
            uses += 1
            self.report["uses"] = uses
            self._log(on_progress, f"已使用司南 {uses} 次")
            if self._sleep(3.0, should_stop):
                break

            # 3.2 每次使用后先检查是否已不可用（出现即停，不关心数值）
            if self._check_unavailable(on_progress):
                self._log(on_progress, "司南已不可用，停止使用")
                break

            # 3.3 处理触发的宝箱/村庄事件（可多个）
            if self._handle_event(on_progress, should_stop):
                if self._sleep(self.wait_after, should_stop):
                    break
            else:
                # 事件为空时，再确认一次是否已不可用
                if self._check_unavailable(on_progress):
                    self._log(on_progress, "司南已不可用，停止使用")
                    break

        # 4. 结束时再确认一次不可用状态
        self._check_unavailable(on_progress)
        return self._finish(on_progress)

    def _handle_event(self, on_progress, should_stop) -> bool:
        """处理一次司南触发的事件（宝箱/村庄/确认/关奖励）。返回是否处理过。"""
        handled = False

        # 宝箱领取确认弹窗：识别到就点绿色"确定"按钮（直接领取宝箱奖励）
        chest_confirm = self._wait_find("sinan_chest_confirm_btn.png",
                                        "宝箱领取确认(确定)", on_progress,
                                        should_stop)
        if chest_confirm:
            self._click(chest_confirm["cx"], chest_confirm["cy"],
                        "确认领取宝箱", on_progress)
            self.report["chests"] += 1
            handled = True
            if self._sleep(self.wait_after, should_stop):
                return handled

        # 宝箱：识别到就点
        chest = self._find("sinan_chest.png", "宝箱", on_progress)
        if chest:
            self._click(chest["cx"], chest["cy"], "收取宝箱", on_progress)
            self.report["chests"] += 1
            handled = True
            if self._sleep(1.5, should_stop):
                return handled

        # 村庄弹窗：识别到就点 → 再点确认按钮
        village = self._find("sinan_village_popup.png", "村庄弹窗", on_progress)
        if village:
            self._click(village["cx"], village["cy"], "收取村民", on_progress)
            self.report["villages"] += 1
            handled = True
            if self._sleep(self.wait_after, should_stop):
                return handled
            confirm = self._wait_find("sinan_village_confirm_btn.png",
                                      "村庄确认按钮", on_progress, should_stop)
            if confirm:
                self._click(confirm["cx"], confirm["cy"], "确认村庄", on_progress)
                if self._sleep(1.5, should_stop):
                    return handled
            else:
                # 兜底：固定坐标点确认
                self._log(on_progress, "确认按钮未识别，用固定坐标兜底")
                self._click(640, 500, "兜底确认", on_progress)
                if self._sleep(1.0, should_stop):
                    return handled

        # 关闭奖励弹窗（固定坐标，点空白处）
        if handled:
            self._click(640, 500, "关闭奖励弹窗（空白处）", on_progress)
            if self._sleep(self.wait_after, should_stop):
                return handled
            self._click(640, 300, "关闭奖励弹窗（第2下）", on_progress)
            if self._sleep(1.5, should_stop):
                return handled

        return handled

    def _check_unavailable(self, on_progress) -> bool:
        """识别不可用百分比 → 标记结束。命中返回 True。"""
        r = self._find("sinan_unavailable_percent.png", "剩余司南不足(不可用)",
                       on_progress)
        if r:
            self.report["unavailable"] = True
            return True
        return False

    def _finish(self, on_progress) -> dict:
        self.report["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._log(on_progress,
                  f"司南任务结束：使用 {self.report['uses']} 次，"
                  f"宝箱 {self.report['chests']} 个，"
                  f"村民 {self.report['villages']} 次，"
                  f"不可用={self.report['unavailable']}")
        return self.report