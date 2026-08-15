"""辅助交易引擎：在交易行自动扫描玩家关注的物品的上架与求购信息。

流程（竖屏 720x1280）：
1. 主界面点主按钮 → 打开功能面板
2. 功能面板里点「交易」入口 → 进入交易行
3. 交易行内切到「关注」页签，读取玩家关注的物品列表
4. 对每个关注物品，切换到对应页签（上架/求购）查看其价格与数量信息
5. 汇总扫描结果并返回报告

本引擎为纯逻辑，不涉及线程/UI；controller 由 TaskRunner 在同线程内调用。
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("sangui.trade")


class TradeItem:
    """交易行里一个关注物品的扫描结果（订单簿模型）。

    sell_levels / buy_levels 为多档挂单，每档 {price, count}，类似股票盘口：
    - sell_levels：出售（上架）方向，按价格从低到高排序
    - buy_levels：求购（收购）方向，按价格从高到低排序
    """

    def __init__(self, name: str = ""):
        self.name = name
        # 出售（上架）方向的多档挂单
        self.sell_levels: list[dict] = []
        # 求购（收购）方向的多档挂单
        self.buy_levels: list[dict] = []
        # 扫描过程中的提示/错误
        self.notes: list[str] = []
        # 来源：关注列表 / 手动
        self.source: str = "关注"

    @property
    def sell_available(self) -> bool:
        return bool(self.sell_levels)

    @property
    def buy_available(self) -> bool:
        return bool(self.buy_levels)

    def __repr__(self):
        return (f"<TradeItem {self.name} 出售:{self.sell_levels} "
                f"求购:{self.buy_levels}>")


class TradeEngine:
    """辅助交易扫描引擎（纯逻辑）。"""

    # 关注列表页签/按钮关键词
    FOCUS_KEYWORDS = ["关注", "收藏", "我的关注"]

    # 上架 / 求购 页签关键词
    SELL_KEYWORDS = ["上架", "出售", "寄售", "卖"]
    BUY_KEYWORDS = ["求购", "收购", "买"]

    # 价格/数量正则
    PRICE_RE = re.compile(r"(\d[\d,，]*)(?:\s*(?:铜|银|金|币|两|文))?")
    COUNT_RE = re.compile(r"(\d[\d,，]*)\s*件")

    # 交易列表里的噪音文本（页签/表头/按钮）
    LIST_NOISE = {
        "上架", "求购", "关注", "交易", "出售", "收购", "价格", "单价",
        "数量", "库存", "物品", "道具", "搜索", "刷新", "全部", "装备",
        "配方", "材料", "宝石", "丹药", "技能", "兵书", "坐骑", "宠物",
        "武器", "防具", "时装", "包裹", "背包", "返回", "关闭",
    }

    def __init__(self, ctrl, params: Optional[dict] = None):
        self.ctrl = ctrl
        p = params or {}
        # 功能面板区域 ROI（点击主按钮后弹出的面板）—— 竖屏 720x1280
        self.panel_roi: tuple[int, int, int, int] = p.get(
            "panel_roi", (0, 0, 720, 1280))
        # 交易行列表区域 ROI（物品列表）
        self.list_roi: tuple[int, int, int, int] = p.get(
            "list_roi", (0, 200, 720, 900))
        # 等待动画时间（s）
        self.wait_anim: float = p.get("wait_anim", 1.0)
        # 连续多少屏无新物品则停止滚动
        self.scroll_idle_limit: int = p.get("scroll_idle_limit", 2)
        # 最大滚动次数
        self.max_scrolls: int = p.get("max_scrolls", 15)
        # 关注物品是否从游戏内关注列表读取（True）还是仅手动（False）
        self.use_focus_list: bool = p.get("use_focus_list", True)
        # 手动指定的关注物品（use_focus_list=False 或用关注列表读取失败时兜底）
        self.focus_items: list[str] = p.get("focus_items", [])
        # 诊断报告
        self.report: dict = {
            "params": self._dump_params(),
            "items": [],
            "errors": [],
            "started_at": "",
            "finished_at": "",
            "total": 0,
        }

    def _dump_params(self) -> dict:
        return {
            "panel_roi": list(self.panel_roi),
            "list_roi": list(self.list_roi),
            "wait_anim": self.wait_anim,
            "scroll_idle_limit": self.scroll_idle_limit,
            "max_scrolls": self.max_scrolls,
            "use_focus_list": self.use_focus_list,
            "focus_items": self.focus_items,
        }

    # ---------------- 主流程 ----------------

    def run(
        self,
        on_progress: Optional[Callable[[str], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> dict:
        """执行一次辅助交易扫描，返回统计报告。"""
        self.report["started_at"] = datetime.now().isoformat(timespec="seconds")

        # 0. 导航：从主界面进入交易行
        if not self._navigate_to_trade(on_progress):
            self.report["errors"].append("进入交易行失败")
            self.report["finished_at"] = datetime.now().isoformat(timespec="seconds")
            return self.report

        # 1. 读取关注物品列表
        focus_names = self._read_focus_items(on_progress)
        if not focus_names:
            focus_names = self.focus_items
            if on_progress:
                on_progress(f"关注列表为空，使用手动指定物品：{focus_names}")
        if not focus_names:
            if on_progress:
                on_progress("错误：没有可关注的物品")
            self.report["finished_at"] = datetime.now().isoformat(timespec="seconds")
            return self.report

        # 2. 逐个物品扫描上架/求购信息
        items: list[TradeItem] = []
        for idx, name in enumerate(focus_names, 1):
            if should_stop and should_stop():
                break
            if on_progress:
                on_progress(f"[{idx}/{len(focus_names)}] 扫描物品：{name}")
            item = TradeItem(name)
            self._scan_item(item, on_progress, should_stop)
            items.append(item)
            if should_stop and should_stop():
                break

        self.report["items"] = [self._item_to_report(it) for it in items]
        self.report["total"] = len(items)
        self.report["finished_at"] = datetime.now().isoformat(timespec="seconds")
        if on_progress:
            on_progress(f"辅助交易扫描结束：共 {len(items)} 个关注物品")
        return self.report

    # ---------------- 导航 ----------------

    def _navigate_to_trade(self, on_progress) -> bool:
        """从主界面进入交易行。返回是否成功。"""
        # 1. 点击功能面板主按钮
        ok = self._click_template(
            "trade_main_btn.png",
            threshold=0.6,
            max_retries=5,
            wait_after=1.5,
            on_progress=on_progress,
            desc="功能面板主按钮",
        )
        if not ok:
            if on_progress:
                on_progress("错误：未找到功能面板主按钮")
            return False
        if on_progress:
            on_progress("已打开功能面板")

        # 2. 点击交易入口
        ok = self._click_template(
            "trade_entry.png",
            threshold=0.6,
            max_retries=5,
            wait_after=1.5,
            on_progress=on_progress,
            desc="交易入口",
        )
        if not ok:
            # 模板匹配失败，尝试 OCR 兜底
            if on_progress:
                on_progress("交易入口模板未命中，尝试 OCR 识别...")
            ok = self._click_keyword("交易", max_retries=3, wait_after=1.5)
        if not ok:
            if on_progress:
                on_progress("错误：未找到交易入口")
            return False
        if on_progress:
            on_progress("已进入交易行")
        return True

    # ---------------- 关注物品读取 ----------------

    def _read_focus_items(self, on_progress=None) -> list[str]:
        """读取游戏内『关注』列表，返回物品名列表。

        优先点交易行内的『关注』页签/按钮读取；读取失败或未开启时返回空。
        """
        if not self.use_focus_list:
            return []
        # 尝试点击『关注』页签
        clicked = self._click_keyword("关注", max_retries=2, wait_after=1.0)
        if not clicked:
            if on_progress:
                on_progress("未找到『关注』页签，将使用手动物品列表")
            return []
        if on_progress:
            on_progress("已切换到『关注』列表")

        # 滚动读取关注物品名列表
        names = self._read_item_names(on_progress)
        if not names:
            if on_progress:
                on_progress("关注列表为空或读取失败")
            return []
        return names

    def _read_item_names(self, on_progress=None) -> list[str]:
        """滚动读取当前列表里的所有物品名，返回去重后的名称列表。"""
        seen: dict[str, int] = {}
        idle = 0
        for _ in range(self.max_scrolls + 1):
            try:
                results = self.ctrl.ocr(roi=self.list_roi)
            except Exception as e:  # noqa: BLE001
                logger.warning("列表 OCR 失败: %s", e)
                break
            names = self._extract_item_names(results)
            new_found = 0
            for n in names:
                if n not in seen:
                    seen[n] = 1
                    new_found += 1
            if on_progress:
                on_progress(f"本屏识别到 {len(names)} 个物品，新增 {new_found}，累计 {len(seen)}")
            if new_found == 0:
                idle += 1
                if idle >= self.scroll_idle_limit:
                    break
            else:
                idle = 0
            self._scroll_list_down()
        self._scroll_to_top()
        return list(seen.keys())

    def _extract_item_names(self, results: list[dict]) -> list[str]:
        """从 OCR 结果里提取合法物品名（过滤噪音）。"""
        names = []
        for r in results:
            text = (r.get("text") or "").strip()
            if not text:
                continue
            if len(text) < 2:
                continue
            if text in self.LIST_NOISE:
                continue
            # 过滤含价格/数量特征的行（"xx铜 y件"）
            if re.search(r"\d.*[件铜银金币两]", text):
                continue
            # 过滤纯数字/纯符号
            if re.match(r"^[\d+\-/.%]+$", text):
                continue
            chinese = re.findall(r"[\u4e00-\u9fa5]", text)
            if len(chinese) < 2:
                continue
            names.append(text)
        return names

    # ---------------- 单个物品扫描 ----------------

    def _scan_item(self, item: TradeItem, on_progress=None, should_stop=None) -> None:
        """扫描一个物品在上架/求购页签的多档挂单。"""
        # 1. 在出售（上架）页签搜索该物品并读取所有挂单
        self._switch_tab("上架", on_progress)
        sell_levels = self._find_and_read(item.name, on_progress, should_stop)
        item.sell_levels = self._sort_sell(sell_levels)
        if not item.sell_levels:
            item.notes.append("出售列表未找到该物品")

        # 2. 切换到求购页签读取
        if should_stop and should_stop():
            return
        self._switch_tab("求购", on_progress)
        buy_levels = self._find_and_read(item.name, on_progress, should_stop)
        item.buy_levels = self._sort_buy(buy_levels)
        if not item.buy_levels:
            item.notes.append("求购列表未找到该物品")

        if on_progress:
            on_progress(
                f"  {item.name}：出售{len(item.sell_levels)}档 / "
                f"求购{len(item.buy_levels)}档"
            )

    @staticmethod
    def _sort_sell(levels: Optional[list]) -> list:
        """出售（上架）方向：价格从低到高排序。"""
        if not levels:
            return []
        return sorted(
            [lv for lv in levels if (lv.get("price") or 0) > 0],
            key=lambda lv: lv["price"],
        )

    @staticmethod
    def _sort_buy(levels: Optional[list]) -> list:
        """求购（收购）方向：价格从高到低排序。"""
        if not levels:
            return []
        return sorted(
            [lv for lv in levels if (lv.get("price") or 0) > 0],
            key=lambda lv: lv["price"],
            reverse=True,
        )

    def _switch_tab(self, tab_keyword: str, on_progress=None) -> None:
        """切换到指定页签（上架/求购）。"""
        self._click_keyword(tab_keyword, max_retries=2, wait_after=1.0)
        if on_progress:
            on_progress(f"已切换到[{tab_keyword}]页签")

    def _search_item(self, name: str, on_progress=None) -> bool:
        """在搜索框输入物品名并搜索。返回是否成功找到搜索框。"""
        # 尝试点击搜索框并输入文本（竖屏 720x1280 下搜索框通常在顶部）
        try:
            results = self.ctrl.ocr(roi=self.list_roi)
            for r in results:
                text = (r.get("text") or "").strip()
                if "搜索" in text or "输入物品" in text:
                    box = r.get("box", (0, 0, 0, 0))
                    cx = box[0] + box[2] // 2
                    cy = box[1] + box[3] // 2
                    self.ctrl.click(cx, cy)
                    time.sleep(0.5)
                    self.ctrl.input_text(name)
                    time.sleep(1.0)
                    if on_progress:
                        on_progress(f"已搜索物品：{name}")
                    return True
        except Exception as e:  # noqa: BLE001
            logger.debug("搜索物品失败: %s", e)
        return False

    def _find_and_read(self, name: str, on_progress=None,
                       should_stop=None) -> list[dict]:
        """在当前页签列表里查找指定物品，读取其全部挂单。

        先尝试搜索框精确搜索；若无法搜索，则滚动列表查找。
        返回 [{price, count}, ...] 挂单列表（可能与物品同名多档）。
        """
        # 尝试搜索框搜索（更精确）
        if self._search_item(name, on_progress):
            # 等搜索结果刷新
            if self._sleep_interruptible(1.0, should_stop):
                return []
            try:
                results = self.ctrl.ocr(roi=self.list_roi)
            except Exception as e:  # noqa: BLE001
                logger.warning("搜索结果 OCR 失败: %s", e)
                return []
            return self._find_rows_for_item(results, name, on_progress)

        # 搜索框不可用：滚动列表查找
        levels: list[dict] = []
        seen_y: set[int] = set()
        idle = 0
        for _ in range(self.max_scrolls + 1):
            if should_stop and should_stop():
                return levels
            try:
                results = self.ctrl.ocr(roi=self.list_roi)
            except Exception as e:  # noqa: BLE001
                logger.warning("列表 OCR 失败: %s", e)
                break
            # 收集本屏该物品的所有挂单
            found = self._find_rows_for_item(results, name, on_progress)
            for lv in found:
                key = (lv.get("price", 0), lv.get("count", 0))
                if key in seen_y:
                    continue
                seen_y.add(key)
                levels.append(lv)
            if not found:
                idle += 1
                if idle >= self.scroll_idle_limit:
                    break
            else:
                idle = 0
            self._scroll_list_down()
            if self._sleep_interruptible(0.5, should_stop):
                return levels
        self._scroll_to_top()
        return levels

    def _find_rows_for_item(self, results: list[dict], name: str,
                            on_progress=None) -> list[dict]:
        """在一屏 OCR 结果里找到指定物品的所有挂单行，解析价格与数量。

        交易行列表结构类似股票盘口：同一物品可有多行不同价格/数量的挂单。
        返回 [{price, count}, ...]。
        """
        items = []
        for r in results:
            text = (r.get("text") or "").strip()
            if not text:
                continue
            box = r.get("box", (0, 0, 0, 0))
            items.append({"text": text, "x": box[0], "y": box[1],
                          "w": box[2], "h": box[3]})
        items.sort(key=lambda it: it["y"])

        rows = self._group_into_rows(items)
        levels: list[dict] = []
        row_count = 0
        for row in rows:
            row_text = "".join(it["text"] for it in row)
            if name not in row_text and row_text not in name:
                continue
            row_count += 1
            price = self._parse_price(row)
            count = self._parse_count(row)
            if price > 0 or count > 0:
                levels.append({"price": price, "count": count})
        if on_progress and levels:
            on_progress(f"  找到 {name}：{row_count} 行挂单")
        return levels

    def _parse_price(self, row: list[dict]) -> int:
        """解析一行里的单价。优先找带货币单位的数字。"""
        for it in row:
            t = it["text"]
            m = self.PRICE_RE.search(t)
            if m and ("铜" in t or "金" in t or "银" in t or "币" in t or "两" in t or "文" in t):
                return self._to_int(m.group(1))
        row_text = "".join(it["text"] for it in row)
        m = self.PRICE_RE.search(row_text)
        if m:
            return self._to_int(m.group(1))
        return 0

    def _parse_count(self, row: list[dict]) -> int:
        """解析一行里的数量（件数）。"""
        for it in row:
            m = self.COUNT_RE.search(it["text"])
            if m:
                return self._to_int(m.group(1))
        return 0

    def _group_into_rows(self, items: list[dict]) -> list[list[dict]]:
        """把 OCR 条目按 y 相近分组为若干行。"""
        rows: list[list[dict]] = []
        for it in items:
            placed = False
            for row in rows:
                ref = row[0]
                if abs(it["y"] - ref["y"]) < 25:
                    row.append(it)
                    placed = True
                    break
            if not placed:
                rows.append([it])
        return rows

    # ---------------- 滚动 ----------------

    def _scroll_list_down(self) -> None:
        """向下滚动列表（内容上移，露出下方）。"""
        x, y, w, h = self.list_roi
        xc = x + w // 2
        self.ctrl.swipe(xc, y + int(h * 0.7), xc, y + int(h * 0.3), duration_ms=300)
        time.sleep(self.wait_anim)

    def _scroll_to_top(self) -> None:
        """回滚到列表顶部。"""
        x, y, w, h = self.list_roi
        xc = x + w // 2
        for _ in range(self.max_scrolls):
            self.ctrl.swipe(xc, y + int(h * 0.3), xc, y + int(h * 0.7), duration_ms=200)
            time.sleep(0.3)

    # ---------------- 通用工具 ----------------

    def _click_template(self, template: str, threshold: float = 0.7,
                        max_retries: int = 3, wait_after: float = 1.0,
                        on_progress=None, desc: str = "") -> bool:
        """通过模板匹配找到并点击。返回是否成功。"""
        for i in range(max_retries):
            try:
                boxes = self.ctrl.recognize(template, threshold)
                if boxes:
                    x, y, w, h, s = boxes[0]
                    cx, cy = x + w // 2, y + h // 2
                    self.ctrl.click(cx, cy)
                    time.sleep(wait_after)
                    if on_progress:
                        on_progress(f"点击{desc}：({cx},{cy}) score={s:.2f}")
                    return True
            except Exception as e:  # noqa: BLE001
                logger.debug("模板匹配失败 %s: %s", template, e)
            time.sleep(0.5)
        return False

    def _click_keyword(self, keyword: str, max_retries: int = 3,
                       wait_after: float = 1.0) -> bool:
        """通过 OCR 找到含有关键词的文本并点击其中心。返回是否成功。"""
        for i in range(max_retries):
            try:
                results = self.ctrl.ocr()
                best = None
                for r in results:
                    text = (r.get("text") or "").strip()
                    if keyword in text:
                        box = r.get("box", (0, 0, 0, 0))
                        best = box
                        break
                if best:
                    cx = best[0] + best[2] // 2
                    cy = best[1] + best[3] // 2
                    self.ctrl.click(cx, cy)
                    time.sleep(wait_after)
                    return True
            except Exception as e:  # noqa: BLE001
                logger.debug("OCR 点击失败 %s: %s", keyword, e)
            time.sleep(0.5)
        return False

    @staticmethod
    def _to_int(s: str) -> int:
        try:
            return int(s.replace(",", "").replace("，", ""))
        except ValueError:
            return 0

    def _sleep_interruptible(
        self,
        seconds: float,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """可打断的等待。返回 True 表示停止被请求。"""
        if should_stop is None:
            time.sleep(seconds)
            return False
        end = time.time() + seconds
        while time.time() < end:
            if should_stop():
                return True
            time.sleep(min(0.2, end - time.time()))
        return False

    # ---------------- 报告 ----------------

    def _item_to_report(self, item: TradeItem) -> dict:
        return {
            "name": item.name,
            "source": item.source,
            "sell_levels": item.sell_levels,
            "buy_levels": item.buy_levels,
            "sell_available": item.sell_available,
            "buy_available": item.buy_available,
            "notes": item.notes,
        }

    def save_report(self, path: str | Path | None = None) -> str:
        """保存诊断报告为 JSON，返回文件路径。"""
        from app.utils.logger import LOG_DIR
        out_dir = Path(path) if path else LOG_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fpath = out_dir / f"trade_{ts}.json"
        fpath.write_text(
            json.dumps(self.report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Trade report saved: %s", fpath)
        return str(fpath)