"""战功自动攻城引擎：在大地图优先攻打『敌众我寡且距离近』的城池战事。

流程（1280x720 分辨率下）：
1. 大地图点「情报」按钮 → 打开情报面板
2. 切换「城池战事」页 → 右侧出现战斗地点列表
3. 逐个读取战斗地点条目（OCR 列表），提取已方/敌方兵力与距离
4. 按评分排序：优先敌方兵力远大于己方、且耗时短（距离近）的战斗地点
5. 点击战斗地点 → 点「攻城」→ 读取右侧红色耗时（距离依据）
6. 若无法直接攻打（无攻城按钮/不能出兵），放弃该地点，继续下一个
7. 全部攻打完或无可攻打时结束

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

logger = logging.getLogger("sangui.zhangong")


class BattleLocation:
    """一个战斗地点条目。"""

    def __init__(self, name: str = "", x: int = 0, y: int = 0):
        self.name = name
        self.x = x
        self.y = y
        # 兵力（OCR 可能读不到，用 0 表示未知）
        self.my_troops: int = 0
        self.enemy_troops: int = 0
        # 攻城耗时（s），点击攻城后从右侧红色时间读到；0 表示未判断
        self.cost_time: int = 0
        # 攻击按钮坐标（点击攻城按钮的位置，可选）
        self.attack_btn: tuple[int, int] | None = None
        # 是否可攻打（无法直接攻打时为 False）
        self.attackable: bool = True
        self.skip_reason: str = ""
        # 评分（高=优先）
        self.score: float = 0.0

    def __repr__(self):
        return (f"<BattleLocation {self.name} 我:{self.my_troops} "
                f"敌:{self.enemy_troops} 耗时:{self.cost_time}s "
                f"可攻:{self.attackable} 分:{self.score:.1f}>")


class ZhanGongEngine:
    """战功自动攻城引擎（纯逻辑）。"""

    # 常见不可攻打的提示关键词
    UNAVAILABLE_KEYWORDS = [
        "无法攻打", "不能出兵", "不可攻击", "距离太远", "无法出征",
        "兵力不足", "血量不足", "无法突袭", "无法选择", "不可选择",
        "敬请期待",
    ]

    # 队伍面板里会被 OCR 读到的、但并非真实队伍名的文本（页签/按钮/提示）
    TEAM_NAME_NOISE = {
        "我的队伍", "临时队伍", "兵法", "司南", "补给", "速", "补",
        "攻打", "突围", "民心", "关闭", "出征", "加成", "免费", "驻守",
        "组队", "队伍", "我的",
        "剩余兵力", "剩余", "兵士",
        "暂无队伍", "无队伍", "没有队伍", "暂无",
    }

    # 队伍名前缀噪音：即使后面跟"队"字也不该当人名（页签/UI词被 OCR 截断的变体）
    # 如"我的队"（"我的队伍"页签截断）、"临时队"（"临时队伍"截断）
    TEAM_NAME_PREFIX_NOISE = {
        "我的", "临时", "剩余", "兵法", "司南", "补给", "我的队伍",
        "临时队伍", "攻打", "突围", "民心", "关闭", "出征", "加成",
        "免费", "驻守", "组队", "队伍", "战力", "兵士",
        "暂无", "没有", "无",
    }

    # 队伍状态关键词（OCR 读到但绝非队伍名的状态文本）
    TEAM_STATUS_NOISE = {
        "驻守中", "备战中", "行军中", "出征中", "恢复中", "重伤",
        "在野", "城内", "防守", "驻守",
    }

    # 战斗地点名噪音：OCR 可能读到但绝非真实城池/战斗地点的 UI 文本
    LOCATION_NAME_NOISE = {
        "兵法信息", "护国军", "同盟标记", "战斗地点", "战争状态",
        "我方队伍数量", "敌方队伍数量", "我方兵力", "敌方兵力",
        "城池战事", "情报", "国家", "同盟", "民心",
        "我的队伍", "临时队伍", "战力", "驻守中", "重伤",
        "预计耗时", "一键补兵", "一键前往", "补兵", "攻打",
        "兵法", "司南", "背包", "常规",
        "进攻", "防守", "集结", "撤退",
    }

    # 合法地点名应满足的最小特征：含中文 ≥ 2 个（纯数字/纯符号直接排除）
    LOCATION_MIN_CHINESE = 2

    def __init__(self, ctrl, params: Optional[dict] = None):
        self.ctrl = ctrl
        p = params or {}
        # 战斗地点表格 ROI（城池战事列表，右侧表格区域）—— 横屏 1280x720
        # 覆盖从「战争状态」列到「战斗地点」列的整个表格
        # 依据截图：表格 x 225~1230，y 200~630
        self.list_roi: tuple[int, int, int, int] = p.get(
            "list_roi", (225, 200, 1005, 430))
        # 右侧队伍面板 ROI（点战斗地点后右侧出现的队伍列表）—— 横屏 1280x720
        self.team_panel_roi: tuple[int, int, int, int] = p.get(
            "team_panel_roi", (600, 50, 680, 650))
        # 短促 toast 提示区域（中上部，如“血量不足/无法攻打”）
        # 依据截图 MuMu-20260814-160607-496.png：toast 出现在 (435,242,185,52)
        # 收窄到其浮动安全范围，避免全屏 OCR 噪音
        self.toast_roi: tuple[int, int, int, int] = p.get(
            "toast_roi", (380, 200, 520, 130))
        # 等待动画时间（s）
        self.wait_anim: float = p.get("wait_anim", 1.0)
        # 敌我兵力倍率阈值：敌方兵力 > 我方 * ratio 才视为值得打
        self.enemy_ratio: float = p.get("enemy_ratio", 2.0)
        # 跳过耗时探测（直接按兵力评分排序开打，避免探测期间列表变化）
        self.skip_probe: bool = p.get("skip_probe", False)
        # 距离耗时上限（s）：超过则认为太远，放弃
        self.max_cost_time: int = p.get("max_cost_time", 600)
        # 优先城市列表（用户配置，比对用）
        self.priority_cities: list[str] = p.get(
            "priority_cities", [])
        # 最大攻打次数（防止失控）
        self.max_attacks: int = p.get("max_attacks", 20)
        # 最大站点尝试数
        self.max_locations: int = p.get("max_locations", 50)
        # 列表滚动识别：最大滚动次数（防止无限滚动）
        self.max_scrolls: int = p.get("max_scrolls", 20)
        # 列表滚动识别：连续多少次无新地点则停止
        self.scroll_idle_limit: int = p.get("scroll_idle_limit", 2)
        # 列表滚动每次上滑距离（px）
        self.scroll_step: int = p.get("scroll_step", 180)
        # 每个地点最大攻打次数（防止重复攻打失控）
        self.max_attacks_per_loc: int = p.get("max_attacks_per_loc", 15)
        # 出战队伍名称（优先匹配；支持多个，逗号分隔）
        self.team_name: str = p.get("team_name", "")
        # 出战队伍序号（1-based，名称匹配失败时用序号兜底）
        self.team_index: int = p.get("team_index", 1)
        # 勾选的可出战队伍名称列表（UI 勾选生成；非空时轮流使用这些队伍）
        self.team_names: list[str] = p.get("team_names", [])
        # 是否粮食耗尽（补兵失败达到终点信号）
        self._food_exhausted: bool = False
        # 本会话内已尝试攻打但失败（非粮尽）的城市，避免下一轮无限重试同一座
        self._blocked_cities: set[str] = set()
        # 诊断报告
        self.report: dict = {
            "params": self._dump_params(),
            "locations": [],
            "attacks": [],
            "skipped": [],
            "errors": [],
            "started_at": "",
            "finished_at": "",
            "total_attacks": 0,
            "defeat_count": 0,
        }

    def _dump_params(self) -> dict:
        return {
            "list_roi": list(self.list_roi),
            "team_panel_roi": list(self.team_panel_roi),
            "toast_roi": list(self.toast_roi),
            "wait_anim": self.wait_anim,
            "enemy_ratio": self.enemy_ratio,
            "max_cost_time": self.max_cost_time,
            "priority_cities": self.priority_cities,
            "max_attacks": self.max_attacks,
            "max_locations": self.max_locations,
            "max_attacks_per_loc": self.max_attacks_per_loc,
            "max_scrolls": self.max_scrolls,
            "scroll_idle_limit": self.scroll_idle_limit,
            "scroll_step": self.scroll_step,
            "team_name": self.team_name,
            "team_index": self.team_index,
            "team_names": self.team_names,
        }

    # ---------------- 主流程 ----------------

    def run(
        self,
        on_progress: Optional[Callable[[str], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> dict:
        """自动刷战功总入口。

        在用户不点「停止」前持续刷：攻完最优城市后回到大地图，重新读列表、
        打分，继续攻打下一个最优城市，直到以下任一停止条件满足：
          - 粮食耗尽（补兵失败）
          - 手动停止
          - 没有可攻打的城市（全部攻打过或全部失败）
          - 累计攻打次数达到 max_attacks 硬上限（默认20，兜底保证不会无限刷）
        """
        self._food_exhausted = False
        self._blocked_cities.clear()
        total_attacks = 0
        self.report["started_at"] = datetime.now().isoformat(timespec="seconds")
        self.report.pop("errors", None)
        self.report["errors"] = []
        stop_reason = ""

        pass_no = 0
        while not self._food_exhausted:
            if should_stop and should_stop():
                stop_reason = "手动停止"
                break
            # 硬上限兜底：即使粮尽 OCR 漏检，也保证循环有界
            if self.max_attacks > 0 and total_attacks >= self.max_attacks:
                stop_reason = f"达到攻打次数上限（{self.max_attacks} 次）"
                break
            pass_no += 1
            if on_progress:
                on_progress(f"===== 第 {pass_no} 轮刷取（累计攻击 {total_attacks} 次）=====")
            r = self._run_one_pass(on_progress, should_stop)
            total_attacks += r.get("total_attacks", 0)
            # 聚合本轮明细到报告（跨轮累积，供保存诊断用）
            self.report["locations"].extend(r.get("locations", []))
            self.report["attacks"].extend(r.get("attacks", []))
            self.report["skipped"].extend(r.get("skipped", []))
            self.report["errors"].extend(r.get("errors", []))
            # 一轮中没有可攻打城市 → 无需继续
            if r.get("no_target"):
                stop_reason = "没有可攻打的城市"
                break

        self.report["total_attacks"] = total_attacks
        self.report["stop_reason"] = stop_reason or "粮食耗尽"
        self.report["finished_at"] = datetime.now().isoformat(timespec="seconds")
        if on_progress:
            defeats = self.report.get("defeat_count", 0)
            on_progress(
                f"战功刷取结束（{self.report['stop_reason']}）："
                f"共攻打 {total_attacks} 次，战败 {defeats} 次")
        return self.report

    def _run_one_pass(
        self,
        on_progress: Optional[Callable[[str], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> dict:
        """执行一轮刷取（攻打当前最优城市一次）。返回该轮统计。"""
        attacks = 0
        rpt = {
            "locations": [],
            "attacks": [],
            "skipped": [],
            "errors": [],
            "total_attacks": 0,
            "no_target": False,
        }

        # 0. 导航：从大地图进入情报 → 城池战事
        if not self._navigate_to_city_war(on_progress):
            rpt["errors"].append("进入城池战事页面失败")
            return rpt

        # 1. 滚动读取当前战斗地点列表（识别所有城市）
        locations = self._read_all_locations(on_progress, should_stop)
        rpt["locations"] = [self._loc_to_report(lo) for lo in locations]
        if on_progress:
            on_progress(f"识别到 {len(locations)} 个战斗地点")

        # 2. 评分并排序（按兵力初排）
        ranked = self._rank_locations(locations, on_progress)
        if on_progress:
            on_progress(f"筛选出 {len(ranked)} 个可攻打地点")

        # 2.5 预探测各地点耗时（距离），用耗时重新排序
        # 若只有一个可攻打城市，或用户指定跳过探测，则直接打
        if len(ranked) == 1 or self.skip_probe:
            if on_progress:
                reason = "仅一个可攻打城市" if len(ranked) == 1 else "已跳过耗时探测"
                on_progress(f"{reason}，直接攻打")
            ranked = ranked[:1]
        else:
            ranked = self._probe_cost_times(ranked, on_progress, should_stop)
            ranked = self._rank_locations(ranked, on_progress)
        if on_progress:
            on_progress(f"按耗时排序后，待攻打地点：{len(ranked)} 个")

        # 3. 只攻打评分最高的 1 个城市（用所有勾选队伍攻打，队伍都派出后结束）
        if not ranked:
            if on_progress:
                on_progress("没有可攻打的城市，直接结束")
            rpt["no_target"] = True
            rpt["total_attacks"] = attacks
            return rpt

        loc = ranked[0]
        if should_stop and should_stop():
            rpt["total_attacks"] = attacks
            return rpt

        if on_progress:
            on_progress(
                f"攻打最优城市：{loc.name}（我{loc.my_troops} vs 敌{loc.enemy_troops}）")

        ok = self._attack_one(loc, on_progress, should_stop)
        rpt["attacks"].append(self._loc_to_report(loc, attacked=ok))
        if ok:
            attacks += 1
        else:
            rpt["skipped"].append(self._loc_to_report(loc))
            # 本城市攻打失败（非粮尽）→ 本会话内不再重试它，改打别的城市
            if not self._food_exhausted:
                if on_progress:
                    on_progress(f"本轮未能攻打 {loc.name}，后续轮次跳过该城")
                self._blocked_cities.add(loc.name)
        rpt["total_attacks"] = attacks
        return rpt

    # ---------------- 导航 ----------------

    def _navigate_to_city_war(self, on_progress) -> bool:
        """从大地图进入情报面板并切换到城池战事。返回是否成功。"""
        # 最多重试 2 次（OCR/模板都失败时，关面板重开再试）
        for attempt in range(2):
            # 0. 先回到大地图确定状态（点空白处关掉可能存在的面板）
            self._back_to_world_map(on_progress)

            # 1. 点击情报按钮（固定坐标优先，模板匹配兜底）
            ok = self._click_template(
                "zhan_gong_intel_btn.png",
                threshold=0.6,
                max_retries=3,
                wait_after=1.5,
                on_progress=on_progress,
                desc="情报按钮",
            )
            if not ok:
                # 模板没找到，用固定坐标点击情报按钮
                ix, iy = self.INTEL_BTN_COORD
                if on_progress:
                    on_progress(f"模板匹配失败，用固定坐标点情报按钮 ({ix},{iy})")
                self.ctrl.click(ix, iy)
                time.sleep(1.5)

            if on_progress:
                on_progress("已点击情报按钮，等待面板展开...")

            # 2. 切换到城池战事页签（左侧垂直页签）
            #    OCR 优先（直接识别"城池战事"四个字点击，比模板匹配更可靠）
            ok = self._click_text("城池战事", max_retries=3, wait_after=1.5)
            if not ok:
                if on_progress:
                    on_progress("OCR 未找到，尝试模板匹配城池战事页签...")
                ok = self._click_template(
                    "zhan_gong_city_war_tab.png",
                    threshold=0.6,
                    max_retries=3,
                    wait_after=1.5,
                    on_progress=on_progress,
                    desc="城池战事页签",
                )

            if ok:
                if on_progress:
                    on_progress("已切换到城池战事页面")
                return True

            # 失败了，关面板重试
            if on_progress:
                on_progress(f"第 {attempt+1} 次未找到城池战事页签，关面板重试...")
            self._back_to_world_map(None)
            time.sleep(1.0)

        if on_progress:
            on_progress("错误：未找到城池战事页签")
        return False

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

    def _template_found(self, template: str, threshold: float = 0.7) -> bool:
        """只检测模板是否出现在屏幕上（不点击）。返回是否命中。"""
        try:
            boxes = self.ctrl.recognize(template, threshold)
            return bool(boxes)
        except Exception as e:  # noqa: BLE001
            logger.debug("模板检测失败 %s: %s", template, e)
            return False

    def _click_text(self, keyword: str, max_retries: int = 3,
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

# ---------------- 列表读取 ----------------

    # 表头关键词（用于识别并跳过表头行）
    HEADER_KEYWORDS = [
        "战争状态", "敌方", "我方队伍数量", "敌方队伍数量", "战斗地点",
        "状态", "我方兵力", "敌方兵力", "地点",
        "我方队伍", "敌方队伍", "队伍数",
    ]

    # 敌方国家前缀（用于从整行文本中分离地点名和兵力）
    ENEMY_PREFIXES = ["进攻吴国", "进攻蜀国", "进攻魏国",
                      "吴国", "蜀国", "魏国",
                      "吴", "蜀", "魏"]

    def _read_locations(self) -> list[BattleLocation]:
        """OCR 战斗地点表格（单屏），返回 BattleLocation 列表。

        表格结构（5列）：战争状态 | 敌方 | 我方队伍数量 | 敌方队伍数量 | 战斗地点
        解析方式：先找表头行确定每列 x 范围，再把数据行条目按 x 归入对应列。
        """
        try:
            results = self.ctrl.ocr(roi=self.list_roi)
        except Exception as e:  # noqa: BLE001
            logger.warning("战斗地点列表 OCR 失败: %s", e)
            self.report["errors"].append(f"列表OCR失败: {e}")
            return []
        return self._parse_locations_screen(results)

    def _parse_locations_screen(self, results: list[dict]) -> list[BattleLocation]:
        """把一屏 OCR results 解析为战斗地点列表（含去重）。"""
        items = []
        for r in results:
            text = (r.get("text") or "").strip()
            if not text:
                continue
            box = r.get("box", (0, 0, 0, 0))
            items.append({"text": text, "x": box[0], "y": box[1],
                          "w": box[2], "h": box[3]})
        items.sort(key=lambda it: it["y"])

        logger.debug("OCR raw (%d): %s", len(items),
                     [(it["text"], it["x"], it["y"]) for it in items])

        # 按行分组
        rows = self._group_into_rows(items)
        if not rows:
            return []

        # 找表头行，确定列边界
        col_edges = self._find_column_edges(rows)

        locations = []
        for row in rows:
            if self._is_header_row(row):
                continue
            loc = self._parse_table_row(row, col_edges)
            if loc and self._is_valid_location(loc):
                locations.append(loc)
            else:
                logger.info("过滤掉行: %s",
                            [(it["text"], it["x"], it["y"]) for it in row])
        return locations

    def _read_all_locations(
        self,
        on_progress=None,
        should_stop=None,
    ) -> list[BattleLocation]:
        """滚动读取整个城池战事列表，返回去重后的全部战斗地点。

        策略：从列表顶部开始，每屏 OCR 解析 → 去重 → 向上滚动一屏，
        直到连续 `scroll_idle_limit` 屏无新地点或达到 `max_scrolls`。
        结束后回滚到列表顶部。
        """
        seen: dict[str, BattleLocation] = {}
        idle = 0
        prev_screen_names: set[str] = set()

        # 先滚到列表顶部，确保从头开始读
        self._scroll_to_top()
        if on_progress:
            on_progress("已滚动到列表顶部，开始读取...")

        for scroll_no in range(self.max_scrolls + 1):
            if should_stop and should_stop():
                break
            try:
                results = self.ctrl.ocr(roi=self.list_roi)
            except Exception as e:  # noqa: BLE001
                logger.warning("滚动列表 OCR 失败: %s", e)
                break
            screen_locs = self._parse_locations_screen(results)
            screen_names = {loc.name for loc in screen_locs}

            # 本屏和上一屏完全一样 → 已到底部，停止
            if screen_names and screen_names == prev_screen_names:
                if on_progress:
                    on_progress(
                        f"滚动 {scroll_no}: 内容与上一屏相同，已到底部，停止滚动")
                break
            prev_screen_names = screen_names

            new_found = 0
            for loc in screen_locs:
                key = loc.name
                if key not in seen:
                    seen[key] = loc
                    new_found += 1
            if on_progress:
                on_progress(
                    f"滚动 {scroll_no}: 本屏{len(screen_locs)}个，新增{new_found}个，累计{len(seen)}个")
            if new_found == 0:
                idle += 1
                if idle >= self.scroll_idle_limit:
                    break
            else:
                idle = 0
            # 向上滚动一屏（列表可拖动）
            self._scroll_list_down()
        # 回滚到列表顶部
        self._scroll_to_top()
        return list(seen.values())

    def _scroll_list_down(self) -> None:
        """向上滑动列表（内容向下滚动，露出下方更多城市）。

        手机列表：手指从下往上滑（y 大→y 小），列表内容才向下滚动露出后续项。
        用 scroll_step 控制滚动距离（约 2/3 屏高），避免跳太多或太少。
        滚动后等待动画稳定，避免 OCR 读到模糊/错位内容。
        """
        x, y, w, h = self.list_roi
        xc = x + w // 2
        step = self.scroll_step
        # 起点在列表偏下方，终点在列表偏上方，距离 = step
        start_y = y + h // 2 + step // 2
        end_y = y + h // 2 - step // 2
        # 限制不超出列表范围
        start_y = min(start_y, y + h - 30)
        end_y = max(end_y, y + 30)
        self.ctrl.swipe(xc, start_y, xc, end_y, duration_ms=500)
        # 等待滚动动画稳定后再 OCR
        time.sleep(max(self.wait_anim, 1.2))

    def _scroll_to_top(self) -> None:
        """反复下拉（内容回到顶部）直到列表回到顶部。

        手机列表：手指从上往下滑（y 小→y 大），列表内容向上滚动回到顶部。
        用连续多次大跨度下滑确保回到顶部，最后等动画稳定。
        """
        x, y, w, h = self.list_roi
        xc = x + w // 2
        # 从接近顶部滑到底部附近，每次滑 h-60，确保最大限度滚动
        top_y = y + 40
        bottom_y = y + h - 40
        for _ in range(6):
            self.ctrl.swipe(xc, top_y, xc, bottom_y, duration_ms=500)
            time.sleep(0.5)
        # 等动画完全稳定
        time.sleep(1.0)

    def _find_column_edges(self, rows: list[list[dict]]) -> list[int]:
        """从表头行确定列边界（每列的 x 中心分隔线）。

        返回 n 个分界 x 坐标，把平面切成 n+1 个列区间。
        如果找不到表头，返回空列表，调用方需做兜底。
        """
        header_row = None
        for row in rows:
            if self._is_header_row(row):
                header_row = row
                break
        if not header_row:
            logger.debug("未找到表头行，列边界推导失败")
            return []

        # 按 x 排序表头各条目
        sorted_items = sorted(header_row, key=lambda it: it["x"])
        edges = []
        for i in range(len(sorted_items) - 1):
            # 两列之间的中线作为分界
            right_of_left = sorted_items[i]["x"] + sorted_items[i]["w"]
            left_of_right = sorted_items[i + 1]["x"]
            edges.append((right_of_left + left_of_right) // 2)
        logger.debug("列边界: %s", edges)
        return edges

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

    def _is_header_row(self, row: list[dict]) -> bool:
        """判断是否为表头行。"""
        header_count = 0
        for it in row:
            for kw in self.HEADER_KEYWORDS:
                if kw in it["text"]:
                    header_count += 1
                    break
        return header_count >= 2  # 命中≥2个表头关键词

    def _parse_table_row(self, row: list[dict],
                         col_edges: list[int]) -> Optional[BattleLocation]:
        """从表格行解析一个战斗地点。

        col_edges: 列边界 x 坐标列表（n 个边 → n+1 列）
        列顺序：[0]战争状态 [1]敌方 [2]我方队伍数量 [3]敌方队伍数量 [4]战斗地点
        """
        if not row:
            return None

        sorted_items = sorted(row, key=lambda it: it["x"])
        all_text = " ".join(it["text"] for it in sorted_items)

        # 列边界有效：按列解析
        if col_edges:
            cols = self._assign_to_columns(row, col_edges)
            if not cols or not cols[-1]:
                return self._parse_row_fallback(row)

            location_col = cols[-1]
            name_text = "".join(it["text"] for it in location_col)
            name = self._clean_city_name(name_text)
            if not name:
                return self._parse_row_fallback(row)

            loc = BattleLocation(name=name)

            rightmost = max(location_col, key=lambda it: it["x"] + it["w"])
            loc.x = rightmost["x"] + rightmost["w"] // 2
            loc.y = rightmost["y"] + rightmost["h"] // 2

            if len(cols) >= 3 and cols[2]:
                my_text = "".join(it["text"] for it in cols[2])
                loc.my_troops = self._parse_troop_number(my_text)

            if len(cols) >= 4 and cols[3]:
                enemy_text = "".join(it["text"] for it in cols[3])
                loc.enemy_troops = self._parse_troop_number(enemy_text)

            if loc.my_troops == 0 or loc.enemy_troops == 0:
                my, enemy = self._extract_troops_fallback(all_text)
                if loc.my_troops == 0:
                    loc.my_troops = my
                if loc.enemy_troops == 0:
                    loc.enemy_troops = enemy
        else:
            # 列边界为空：走智能兜底解析
            loc = self._parse_row_fallback(row)
            if not loc:
                return None

        logger.info("解析 %s: 我=%d 敌=%d", loc.name, loc.my_troops, loc.enemy_troops)
        return loc

    def _is_valid_location(self, loc: BattleLocation) -> bool:
        """判断解析出的战斗地点是否有效，过滤 OCR 噪音。

        规则：
        1. 名称在噪音词表里 → 无效
        2. 名称过短或纯数字/纯符号 → 无效
        3. 中文不足 2 字 → 无效
        4. 含常见 UI 关键词（信息/标记/数量/兵力 等）→ 无效
        5. 敌我兵力都为 0 且名称无国家前缀 → 无效
        """
        name = loc.name.strip()
        if len(name) < 2:
            return False

        if name in self.LOCATION_NAME_NOISE:
            return False

        if re.match(r"^[\d+\-]+$", name):
            return False

        chinese_chars = re.findall(r"[\u4e00-\u9fa5]", name)
        if len(chinese_chars) < self.LOCATION_MIN_CHINESE:
            return False

        ui_keywords = ["信息", "标记", "数量", "兵力", "队伍", "状态",
                       "贡献", "任务", "奖励", "等级", "背包", "设置",
                       "公告", "邮件", "聊天", "活动", "商店", "礼包",
                       "战令", "赛季", "首充", "国势"]
        for kw in ui_keywords:
            if kw in name:
                return False

        # 敌我兵力都为 0：大概率是噪音或解析失败 → 无效
        if loc.enemy_troops == 0 and loc.my_troops == 0:
            return False

        return True

    def _parse_row_fallback(self, row: list[dict]) -> Optional[BattleLocation]:
        """列边界无法确定时的兜底解析：从整行文本中智能提取地点名和兵力。

        策略：
        1. 从右往左找到最右侧带数字的条目 → 敌方兵力
        2. 往左找到下一个带数字的条目 → 我方兵力
        3. 再往左的中文/国家前缀文本 → 地点名
        4. 点击位置：最右侧条目（箭头 > 处）
        """
        if not row:
            return None

        sorted_items = sorted(row, key=lambda it: it["x"])

        # 收集所有带数字的条目（从右往左）
        numeric_items = []
        for it in sorted_items:
            t = it["text"]
            if re.search(r"\d", t) and not re.match(r"^[>\-→]+$", t):
                numeric_items.append(it)

        my_troops = 0
        enemy_troops = 0

        # 敌方兵力：最右侧的数字（或 a+b 格式）
        if numeric_items:
            enemy_item = numeric_items[-1]
            enemy_troops = self._parse_troop_number(enemy_item["text"])

        # 我方兵力：倒数第二个数字条目
        if len(numeric_items) >= 2:
            my_item = numeric_items[-2]
            my_troops = self._parse_troop_number(my_item["text"])

        # 如果还没找到，用正则关键词兜底
        all_text = " ".join(it["text"] for it in sorted_items)
        if my_troops == 0 or enemy_troops == 0:
            my_fb, enemy_fb = self._extract_troops_fallback(all_text)
            if my_troops == 0:
                my_troops = my_fb
            if enemy_troops == 0:
                enemy_troops = enemy_fb

        # 地点名：找含国家前缀或不含数字的中文长文本
        name = self._extract_location_name(sorted_items)
        if not name:
            return None

        loc = BattleLocation(name=name)
        loc.my_troops = my_troops
        loc.enemy_troops = enemy_troops

        # 点击位置：最右侧条目的中心
        rightmost = max(sorted_items, key=lambda it: it["x"] + it["w"])
        loc.x = rightmost["x"] + rightmost["w"] // 2
        loc.y = rightmost["y"] + rightmost["h"] // 2

        return loc

    def _extract_location_name(self, sorted_items: list[dict]) -> str:
        """从按 x 排序的 OCR 条目中提取战斗地点名称。

        策略：
        - 优先找含国家前缀（吴国/蜀国/魏国/进攻X国）的条目
        - 否则找最右侧的非数字中文长文本
        - 去掉末尾的 > 箭头等符号
        """
        # 找含国家前缀的条目
        for it in sorted_items:
            t = it["text"]
            for prefix in self.ENEMY_PREFIXES:
                if prefix in t and len(t) >= 3:
                    name = self._clean_city_name(t)
                    if name:
                        return name

        # 找最右侧的纯中文（含国家/城名）文本作为地点名
        # 表格结构从左到右：战争状态 | 敌方 | 我方数 | 敌方数 | 战斗地点
        # 地点名一定在最右侧，所以从右往左找第一个符合条件的
        for it in reversed(sorted_items):
            t = it["text"]
            if re.search(r"[\u4e00-\u9fa5]{2,}", t) and not re.search(r"\d", t):
                cleaned = self._clean_city_name(t)
                if cleaned:
                    return cleaned

        # 最后兜底：取最右侧文本尝试清理
        for it in reversed(sorted_items):
            t = self._clean_city_name(it["text"])
            if len(t) >= 2:
                return t

        return ""

    def _assign_to_columns(self, row: list[dict],
                           col_edges: list[int]) -> list[list[dict]]:
        """把一行内的 OCR 条目按 x 位置分配到各列。

        col_edges 是 n 个分边 → 产生 n+1 列。
        每条目根据其中心 x 落在哪个区间来归列。
        """
        n_cols = len(col_edges) + 1
        cols: list[list[dict]] = [[] for _ in range(n_cols)]
        for it in row:
            cx = it["x"] + it["w"] // 2
            col_idx = 0
            for edge in col_edges:
                if cx > edge:
                    col_idx += 1
                else:
                    break
            if 0 <= col_idx < n_cols:
                cols[col_idx].append(it)
        return cols

    def _extract_troops_fallback(self, all_text: str) -> tuple[int, int]:
        """兜底：在整行文本里用正则找敌我数量。

        策略：
        1. 先尝试找 "我...数字" 和 "敌...数字" 格式
        2. 找不到则提取所有数字，按从左到右顺序：第1个=我方，最后1个=敌方
           （中间可能有 + 号连接的增援兵，需要识别 a+b 格式）
        """
        my = 0
        enemy = 0

        # 带关键词的正则
        m = re.search(r"我(?:方|军|队伍|兵)?[^0-9]{0,6}(\d+(?:\+\d+)?)", all_text)
        if m:
            my = self._parse_troop_number(m.group(1))
        m2 = re.search(r"敌(?:方|军|队伍|兵)?[^0-9]{0,6}(\d+(?:\+\d+)?)", all_text)
        if m2:
            enemy = self._parse_troop_number(m2.group(1))

        if my > 0 and enemy > 0:
            return my, enemy

        # 纯数字兜底：找所有数字段（支持 a+b）
        num_tokens = re.findall(r"\d+(?:\+\d+)?", all_text)
        if num_tokens:
            if my == 0 and len(num_tokens) >= 2:
                my = self._parse_troop_number(num_tokens[0])
            if enemy == 0:
                enemy = self._parse_troop_number(num_tokens[-1])

        return my, enemy

    @staticmethod
    def _clean_city_name(text: str) -> str:
        """清洗城市名，去除国家前缀、首尾符号（[ ] 》 等）、末尾 > 箭头。

        战斗地点列格式：「吴 彭城」「魏 观阳北」等，前面是国家（徽章+单字），后面是城市名。
        """
        name = text.strip()
        # 去掉首尾的符号类字符（[ ] 》 → 等），OCR 常把它们混进城名
        name = re.sub(r"^[\[〔【（(〔<«『【［]+", "", name)
        name = re.sub(r"[>\]」》〕】）)\]»『』]+$", "", name).strip()
        # 去掉国家前缀：吴国/蜀国/魏国/吴/蜀/魏 + 空格或直接连接
        name = re.sub(r"^[吴蜀魏][国]?[\s·]?", "", name)
        # 去掉进攻前缀
        name = re.sub(r"^进攻[吴蜀魏][国]?", "", name)
        if len(name) < 2:
            return ""
        return name

    @staticmethod
    def _parse_troop_number(text: str) -> int:
        """解析队伍数量。支持："33" / "29+86"（驻守+增援）。"""
        text = text.strip()
        if not text:
            return 0
        # 29+86 → 115
        if "+" in text:
            total = 0
            for part in text.split("+"):
                total += ZhanGongEngine._to_int(part)
            return total
        return ZhanGongEngine._to_int(text)

    @staticmethod
    def _to_int(s: str) -> int:
        try:
            return int(s.replace(",", "").replace("，", ""))
        except ValueError:
            return 0

    # ---------------- 评分 ----------------

    def _probe_cost_times(self, locs: list[BattleLocation],
                          on_progress=None,
                          should_stop=None) -> list[BattleLocation]:
        """预探测各地点的耗时（距离）。

        逐个点击候选城市 → 读取目标队伍预计耗时 → 关闭面板回列表 → 下一个。
        探测完成后用耗时重新评分排序，选出真正值得攻打的（耗时最短优先）。
        """
        if not locs:
            return locs

        if on_progress:
            on_progress(f"预探测 {len(locs)} 个地点的耗时（距离）...")

        probed: list[BattleLocation] = []
        for idx, loc in enumerate(locs):
            if should_stop and should_stop():
                break

            # 重新导航回列表顶部，按城市名定位并点击 → 弹出行动菜单
            if on_progress:
                on_progress(f"探测 {idx + 1}/{len(locs)}：{loc.name}...")
            if not self._click_city_by_name(loc.name, on_progress, should_stop):
                if on_progress:
                    on_progress(f"{loc.name} 定位/点击失败，跳过")
                probed.append(loc)
                continue
            # 识别行动菜单攻打/行军按钮并点击（为读取队伍面板耗时做准备）
            if not self._click_city_action(on_progress):
                if on_progress:
                    on_progress(f"{loc.name} 未找到行动菜单攻打/行军按钮")
            if self._sleep_interruptible(1.0, should_stop):
                break

            teams = self._parse_team_panel(on_progress)
            if teams:
                # 取所有队伍中最短的耗时作为该地点的距离耗时，
                # 与具体选哪支队无关，更能反映"距离远近"
                min_cost = 0
                for t in teams:
                    c = t.get("cost_time") or 0
                    if c > 0 and (min_cost == 0 or c < min_cost):
                        min_cost = c
                loc.cost_time = min_cost
                if on_progress:
                    time_show = f"{loc.cost_time}秒" if loc.cost_time > 0 else "未知"
                    on_progress(f"  {loc.name} 预计耗时：{time_show}")
            else:
                if on_progress:
                    on_progress(f"  {loc.name} 未读取到队伍面板，耗时未知")

            # 距离太远 → 标记不可打
            if loc.cost_time > 0 and loc.cost_time > self.max_cost_time:
                loc.attackable = False
                loc.skip_reason = (
                    f"距离太远（耗时{loc.cost_time}s > {self.max_cost_time}s）")
                if on_progress:
                    on_progress(f"  放弃：{loc.name}（{loc.skip_reason}）")

            probed.append(loc)

            # 关闭面板，回到列表，探测下一个
            self._close_team_panel()
            if self._sleep_interruptible(self.wait_anim, should_stop):
                break
            # 重新导航回城池战事列表（确保每个探测都在列表页触发）
            self._navigate_to_city_war(on_progress)
            locs_after = self._read_locations()
            if len(locs_after) != len(locs):
                # 列表行数变化，重新映射坐标到当前列表
                by_name = {lo.name: lo for lo in locs_after}
                for ploc in probed:
                    cur = by_name.get(ploc.name)
                    if cur:
                        ploc.x, ploc.y = cur.x, cur.y

        return probed

    def _click_city_by_name(self, name: str,
                            on_progress=None,
                            should_stop=None) -> bool:
        """重新导航回城池战事列表顶部，按城市名定位并点击该城市。

        解决滚动后坐标失效问题：每次点击前都重开情报窗口回到列表顶部，
        在列表顶部通过 OCR 定位城市名，使用当屏坐标点击，不依赖滚动前坐标。

        若顶部一屏找不到该城市，自动向下滚动搜索（最多 max_scrolls 次），
        找到后点击；滚动到底仍找不到则返回 False。

        返回是否成功点击到该城市。
        """
        if on_progress:
            on_progress(f"[定位] 重开情报窗口回顶，定位城市『{name}』...")

        # 1. 重新导航到城池战事列表顶部
        if not self._navigate_to_city_war(on_progress):
            if on_progress:
                on_progress(f"[定位] 无法回到城池战事页面，放弃『{name}』")
            return False

        # 先滚到列表顶部，确保从头开始找
        self._scroll_to_top()

        # 2. 从顶部开始查找：先读当前屏，找不到则向下滚动继续找
        prev_screen_names: set[str] = set()
        for scroll_idx in range(self.max_scrolls + 1):
            if should_stop and should_stop():
                return False
            locs = self._read_locations()
            if not locs:
                if on_progress:
                    on_progress(f"[定位] 列表OCR为空，放弃『{name}』")
                return False

            target = None
            for lo in locs:
                if lo.name == name or name in lo.name or lo.name in name:
                    target = lo
                    break
            if target:
                if on_progress:
                    on_progress(
                        f"[定位] 在列表({target.x},{target.y})找到"
                        f"『{target.name}』（滚动{scroll_idx}），点击")
                self.ctrl.click(target.x, target.y)
                if self._sleep_interruptible(1.5, should_stop):
                    return False
                return True

            # 本屏未找到
            names = [lo.name for lo in locs]
            screen_set = set(names)

            # 内容和上一屏一样 → 已到底部，不用再找了
            if screen_set == prev_screen_names:
                if on_progress:
                    on_progress(f"[定位] 已到列表底部仍未找到『{name}』，放弃")
                return False
            prev_screen_names = screen_set

            if on_progress:
                on_progress(
                    f"[定位] 滚动{scroll_idx}未找到『{name}』，有: {names}，"
                    f"向下滚动")
            self._scroll_list_down()
            if self._sleep_interruptible(0.8, should_stop):
                return False

        if on_progress:
            on_progress(f"[定位] 滚动到底仍未找到『{name}』，放弃")
        return False

    def _rank_locations(self, locations: list[BattleLocation],
                        on_progress=None) -> list[BattleLocation]:
        """给地点打分并排序，返回建议攻打列表（降序）。

        过滤规则：只攻打「敌方队伍数量 > 我方队伍数量」的地点（敌强我弱/敌多我少），
        排除敌≤我（我方不占优）的地点——这些不在考虑范围内。
        """
        for loc in locations:
            loc.score = self._score(loc)
        ranked = [
            lo for lo in locations
            if lo.attackable and lo.enemy_troops > lo.my_troops
            and lo.name not in self._blocked_cities
        ]
        ranked.sort(key=lambda lo: lo.score, reverse=True)

        if on_progress and ranked:
            lines = ["地点排序（按优先级）:"]
            for i, lo in enumerate(ranked[:10], 1):
                ratio_text = (
                    f"{lo.my_troops}/{lo.enemy_troops}"
                    if lo.enemy_troops > 0 or lo.my_troops > 0
                    else "未知"
                )
                time_text = f"{lo.cost_time}s" if lo.cost_time > 0 else "未知"
                lines.append(
                    f"  {i}. {lo.name}  我/敌={ratio_text}  "
                    f"耗时={time_text}  评分={lo.score:.1f}"
                )
            if len(ranked) > 10:
                lines.append(f"  ... 共 {len(ranked)} 个地点")
            on_progress("\n".join(lines))

        return ranked

    def _score(self, loc: BattleLocation) -> float:
        """计算地点优先级评分。

        依据：
        - 若在优先城市列表：+100
        - 敌我兵力比：**敌>我才优先，比值越大越好**
          - 敌/我 > 1：值得打，比值越大分越高（敌多战功多）
          - 敌/我 < 1：我强敌弱，不值得优先打 → 降分
        - 已读耗时越短（距离近）越优先
        - 读不到兵力/耗时则给中性分
        """
        score = 0.0
        if loc.name and any(
            kw in loc.name for kw in self.priority_cities
        ):
            score += 100.0

        if loc.enemy_troops > 0 and loc.my_troops > 0:
            ratio = loc.enemy_troops / loc.my_troops
            if ratio > 1.0:
                # 敌强我弱/敌多我少：比值越大越优先
                score += min(ratio * 10, 100.0)
            else:
                # 我强敌弱：反向扣分，越悬殊分越低
                score -= min((1.0 / max(ratio, 0.01)) * 10, 100.0)
        elif loc.enemy_troops > 0:
            score += 30.0  # 有敌情但不知我方，给中性偏上分
        elif loc.my_troops > 0 and loc.enemy_troops == 0:
            score -= 20.0  # 只有我方没敌方，不太值得打
        else:
            score -= 10.0  # 敌我都未知，降低优先级

        if loc.cost_time > 0:
            # 耗时越短分越高
            score += max(0.0, 100.0 - loc.cost_time / 6.0)
        elif loc.cost_time == 0:
            score += 10.0  # 未判断耗时，给基础分

        return score

    # ---------------- 攻打 ----------------

    def _attack_one(
        self,
        loc: BattleLocation,
        on_progress: Optional[Callable[[str], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """攻打一个地点。返回是否至少成功攻打过至少一次。

        实际流程（从截图确认）：
        1. 点情报表格里的战斗地点 → 地图定位到该城，右侧弹出队伍列表面板
        2. 在右侧面板找目标队伍（按名称或序号）
        3. 反复循环：等重伤恢复倒计时 → 点补兵（直到无粮/补兵失败）→
           点「攻打」→ 确认出征 → 等待战斗结束并关闭结果，直到无法继续攻打
        """
        try:
            # 1. 重新导航回列表顶部，按城市名定位并点击 → 弹出行动菜单
            if on_progress:
                on_progress(f"点击战斗地点：{loc.name}")
            if not self._click_city_by_name(loc.name, on_progress, should_stop):
                if on_progress:
                    on_progress(f"放弃：{loc.name}（定位/点击失败）")
                return False

            # 1.5 识别行动菜单上的攻打/行军按钮并点击 → 右侧弹出队伍选择面板
            if not self._click_city_action(on_progress):
                if on_progress:
                    on_progress("未找到行动菜单的攻打/行军按钮，尝试直接读队伍面板")
            if self._sleep_interruptible(1.0, should_stop):
                return False

            # 2-3. 解析右侧队伍面板并找到目标队伍（首次，用于校验）
            teams = self._parse_team_panel(on_progress)
            if not teams:
                loc.attackable = False
                loc.skip_reason = "未读取到队伍列表"
                if on_progress:
                    on_progress(f"放弃：{loc.name}（{loc.skip_reason}）")
                self._close_team_panel()
                return False
            target = self._find_target_team(teams, on_progress)
            if not target:
                loc.attackable = False
                loc.skip_reason = (
                    f"未找到目标队伍（名称={self.team_name!r} 序号={self.team_index}）"
                )
                if on_progress:
                    on_progress(f"放弃：{loc.name}（{loc.skip_reason}）")
                self._close_team_panel()
                return False

            # 4. 首次耗时检查（后续循环不再重复检查距离）
            loc.cost_time = target["cost_time"]
            if on_progress:
                if loc.cost_time > 0:
                    on_progress(
                        f"{target['name']} 预计耗时：{loc.cost_time}秒"
                        f"（上限{self.max_cost_time}秒）"
                    )
                else:
                    on_progress(f"{target['name']} 未读取到耗时信息，跳过距离检查")
            if loc.cost_time > 0 and loc.cost_time > self.max_cost_time:
                loc.attackable = False
                loc.skip_reason = f"距离太远（耗时{loc.cost_time}s > {self.max_cost_time}s）"
                if on_progress:
                    on_progress(f"放弃：{loc.name}（{loc.skip_reason}）")
                self._close_team_panel()
                return False

            # 5. 确定本轮要出战的队伍列表：
            #    若用户勾选了 team_names，则逐个队伍攻打；否则用默认目标队伍
            if self.team_names:
                target_teams = []
                for tname in self.team_names:
                    found = self._find_team_by_name(teams, tname)
                    if found:
                        target_teams.append(found)
                    else:
                        if on_progress:
                            on_progress(f"勾选队伍『{tname}』未在面板中找到，跳过")
                if not target_teams:
                    on_progress(f"勾选的队伍都不可用，放弃：{loc.name}")
                    self._close_team_panel()
                    return False
            else:
                target_teams = [target]

            # 6. 第一轮：批量把所有可战队伍各派出一队。
            #    面板保持打开，只需一次导航、一次补兵、一次定位，逐个点攻打按钮，
            #    靠 UNAVAILABLE toast 拦截不可攻打的队伍；全部点完后
            #    关面板回大地图统一验证出征情况，再一起等待所有战斗结束。
            #    后续轮次仍走 _attack_with_team（从第 2 轮继续）。
            if should_stop and should_stop():
                return False

            # 6.1 一键补兵（给所有队伍补满）
            if on_progress:
                on_progress(f"【批量第一轮】一键补兵（{len(target_teams)} 队）")
            clicked = self._click_supply_all_btn(on_progress)
            if clicked:
                if self._sleep_interruptible(1.5, should_stop):
                    return False
                if self._has_no_food():
                    if on_progress:
                        on_progress("补兵失败（无粮食），本轮批量派出放弃")
                    self._food_exhausted = True
                    self._back_to_world_map(on_progress)
                    return False

            # 6.2 面板保持打开，逐个点攻打按钮
            dispatched: list[dict] = []
            for t_idx, tgt in enumerate(target_teams, 1):
                if should_stop and should_stop():
                    break
                if on_progress:
                    on_progress(
                        f"【批量第一轮】派出 {t_idx}/{len(target_teams)}："
                        f"{tgt['name']}")
                self._click_attack_btn_on_team(tgt, on_progress)
                if self._sleep_interruptible(3.0, should_stop):
                    break
                # 点完攻打检测不可攻打 toast，有则跳过该队
                if self._has_toast(
                    self.UNAVAILABLE_KEYWORDS,
                    template="zhan_gong_unavailable.png",
                ):
                    if on_progress:
                        on_progress(
                            f"【批量第一轮】攻打失败（无法攻打提示），"
                            f"跳过：{tgt['name']}")
                    continue
                # 无 toast，视为点上了攻打（可能已直接出征），记录待验证
                dispatched.append(tgt)

            if not dispatched:
                if on_progress:
                    on_progress(f"无队伍成功派出，放弃：{loc.name}")
                self._back_to_world_map(on_progress)
                return False

            # 6.3 全部点完：关面板回大地图，通过 compact 列表验证出征
            self._back_to_world_map(on_progress)
            if self._sleep_interruptible(3.0, should_stop):
                return False
            actually_marching: list[dict] = []
            for tgt in dispatched:
                if should_stop and should_stop():
                    break
                team_name = tgt.get("name", "?")
                if self._verify_team_marching(team_name):
                    actually_marching.append(tgt)
                    if on_progress:
                        on_progress(f"【批量第一轮】派兵成功：{team_name}")
                else:
                    # compact 列表 OCR 可能漏判，点了攻打就按已派出算
                    actually_marching.append(tgt)
                    if on_progress:
                        on_progress(
                            f"【批量第一轮】派兵验证未通过"
                            f"（可能OCR漏判/已派出）：{team_name}")

            if not actually_marching:
                if on_progress:
                    on_progress(
                        f"【批量第一轮】没有队伍验证出征，放弃：{loc.name}")
                return False

            attacked_any = True
            loc.skip_reason = ""

            # 7. 等待所有批量派出的队伍战斗结束（多队伍同时等待）
            if on_progress:
                on_progress(
                    f"【批量第一轮】等待 {len(actually_marching)} 队战斗结束...")
            stopped = self._wait_battle_return_multi(
                loc, actually_marching, on_progress, should_stop)
            if stopped:
                return attacked_any

            # 8. 后续轮次：保持原有单队伍多轮循环逻辑。
            #    每队第 1 轮已由上方批量派出，故从第 2 轮继续。
            for t_idx, tgt in enumerate(target_teams, 1):
                if should_stop and should_stop():
                    break
                # 轮前清理可能已弹出的战败弹窗（上一队后续轮次战斗可能已失败）
                if self._has_result_popup():
                    self._dismiss_result()
                    if on_progress:
                        on_progress("轮前检测到战败弹窗，已关闭")
                if on_progress:
                    on_progress(
                        f"【队伍 {t_idx}/{len(target_teams)}】攻打 {tgt['name']}")
                ok = self._attack_with_team(
                    loc, tgt, on_progress, should_stop,
                    start_round=2)
                if ok:
                    attacked_any = True
                if should_stop and should_stop():
                    break

            return attacked_any

        except Exception as e:  # noqa: BLE001
            logger.exception("攻打异常 %s", loc.name)
            self.report["errors"].append(f"攻打{loc.name}异常: {e}")
            return False

    def _attack_with_team(
        self,
        loc: BattleLocation,
        target: dict,
        on_progress=None,
        should_stop=None,
        start_round: int = 1,
    ) -> bool:
        """用单个队伍循环攻打一个地点。

        每轮流程：
        1. 重新导航到城池战事→定位城市→点攻城→打开队伍面板
        2. 解析队伍面板，找到目标队伍
        3. 出征中（非本次启动）→ 跳过
        4. 重伤 → 关面板回大地图等恢复 → 下一轮
        5. 可攻打 → 补兵 → 点攻打 → 关面板回大地图 → 等战斗结束 → 下一轮

        说明：攻打面板内的预计时间是静态的，不会实时更新。
        派兵后必须回到大地图，通过右侧常驻队伍列表（compact）检测真实状态。

        start_round：从第几轮开始攻打。默认 1（独立调用走完整多轮循环）。
        批量第一轮派出后，后续轮次从 start_round=2 继续，避免重复派第一队。
        """
        attacked_any = False
        defeat_count = 0
        team_name = target.get("name", "?")
        team_index = target.get("index") or 0

        for round_no in range(start_round, self.max_attacks_per_loc + 1):
            if should_stop and should_stop():
                break

            # 0. 轮前清理战败弹窗
            if self._has_result_popup():
                self._dismiss_result()
                defeat_count += 1
                if on_progress:
                    on_progress(
                        f"【第{round_no}轮】战斗失败（第{defeat_count}次），"
                        f"已关闭战败弹窗")
                if self._sleep_interruptible(2.0, should_stop):
                    break

            # 1. 重新导航：从大地图→情报→城池战事→定位城市→点攻城
            ok = self._open_attack_panel_for_city(
                loc, on_progress, should_stop)
            if not ok:
                if on_progress:
                    on_progress(
                        f"【第{round_no}轮】打开攻打面板失败，结束：{loc.name}")
                break

            # 2. 解析队伍面板
            teams = self._parse_team_panel(on_progress)
            if not teams:
                if on_progress:
                    on_progress(
                        f"【第{round_no}轮】未读取到队伍面板，结束：{loc.name}")
                self._back_to_world_map(on_progress)
                break

            target = self._find_team_by_name(teams, team_name)
            if not target and team_index and team_index <= len(teams):
                target = teams[team_index - 1]
            if not target:
                if on_progress:
                    on_progress(
                        f"【第{round_no}轮】未找到目标队伍『{team_name}』，"
                        f"结束：{loc.name}")
                self._back_to_world_map(on_progress)
                break
            team_name = target.get("name", team_name)
            if not target.get("index"):
                target["index"] = team_index

            # 3. 队伍出征中：如果是首次检测且之前没派兵，说明是初始出征中，跳过
            status = target.get("status", "") or ""
            is_marching = any(
                kw in status for kw in ("出征中", "行军中")
            )
            if is_marching:
                if not attacked_any:
                    if on_progress:
                        on_progress(
                            f"队伍已出征（{status}），"
                            f"非本次启动，跳过：{team_name}")
                    self._back_to_world_map(on_progress)
                    break
                # 自己派出去的，继续等
                if on_progress:
                    on_progress(
                        f"【第{round_no}轮】队伍出征中（{status}），等待返回")

            # 4. 重伤 / 兵力不足：先点一键补兵再打，不傻等恢复
            #    补兵后重伤/缺兵都会被补满，直接进入攻打流程。
            #    只有真的点不了攻打（如无粮）才由后续 toast 检测兜底。
            if not target.get("attackable", True):
                if on_progress:
                    on_progress(
                        f"【第{round_no}轮】队伍重伤/不可战，"
                        f"先补兵：{team_name}")
                clicked = self._click_supply_all_btn(on_progress)
                if clicked:
                    if self._sleep_interruptible(2.0, should_stop):
                        break
                    if self._has_no_food():
                        self._food_exhausted = True
                        if on_progress:
                            on_progress(
                                f"补兵失败（无粮食），结束攻打：{team_name}")
                        self._back_to_world_map(on_progress)
                        break
                    # 补兵后重新解析一次，确认状态更新
                    teams = self._parse_team_panel(on_progress)
                    target = self._find_team_by_name(teams, team_name)
                    if not target and team_index:
                        teams2 = self._parse_team_panel(on_progress)
                        if team_index <= len(teams2):
                            target = teams2[team_index - 1]
                    if not target:
                        if on_progress:
                            on_progress(
                                f"【第{round_no}轮】补兵后找不到队伍，"
                                f"结束：{team_name}")
                        self._back_to_world_map(on_progress)
                        break
                    team_name = target.get("name", team_name)

            # 5. 补兵：每轮战斗前点面板底部『一键补兵』大按钮（给全部队伍补兵）。
            # 兵满时点了也无副作用，无需通过血条颜色验证。
            # 无粮情况由 _has_no_food 检测兜底，真没兵则点攻打时 toast 也会拦截。
            if on_progress:
                on_progress(f"【第{round_no}轮】一键补兵：{team_name}")
            clicked = self._click_supply_all_btn(on_progress)
            if not clicked:
                if on_progress:
                    on_progress("未找到一键补兵按钮，跳过补兵直接攻打")
            else:
                if self._sleep_interruptible(1.5, should_stop):
                    break
                if self._has_no_food():
                    self._food_exhausted = True
                    if on_progress:
                        on_progress(
                            f"补兵失败（无粮食），结束攻打：{team_name}")
                self._back_to_world_map(on_progress)
                break

            # 6. 点「攻打」出征 + 验证（用大地图 compact 列表确认）
            if on_progress:
                on_progress(f"【第{round_no}轮】点『攻打』出征：{team_name}")
            attack_ok = False
            for retry in range(2):
                if should_stop and should_stop():
                    break
                if on_progress and retry > 0:
                    on_progress(
                        f"【第{round_no}轮】攻打重试 {retry}/2：{team_name}")
                self._click_attack_btn_on_team(target, on_progress)
                if self._sleep_interruptible(3.0, should_stop):
                    break

                if self._has_toast(
                    self.UNAVAILABLE_KEYWORDS,
                    template="zhan_gong_unavailable.png",
                ):
                    if on_progress:
                        on_progress(
                            f"攻打失败（血量不足/无法攻打提示），"
                            f"放弃：{team_name}")
                    self._back_to_world_map(on_progress)
                    return attacked_any

                # 关面板回大地图，验证是否真的出征
                self._back_to_world_map(on_progress)
                if self._sleep_interruptible(3.0, should_stop):
                    break

                if self._verify_team_marching(team_name):
                    attack_ok = True
                    if on_progress:
                        on_progress(f"【第{round_no}轮】派兵成功，队伍已出征")
                    break

                # 没出征，可能是没兵了（队伍位置因战力排序变化
                # 导致补兵没命中正确队伍）。
                # 重新打开面板，先一键补兵再重试攻打。
                if on_progress:
                    on_progress(
                        f"【第{round_no}轮】派兵验证失败，"
                        f"重新打开面板并一键补兵")
                ok = self._open_attack_panel_for_city(
                    loc, on_progress, should_stop)
                if not ok:
                    break
                self._click_supply_all_btn(on_progress)
                if self._sleep_interruptible(2.0, should_stop):
                    break
                teams = self._parse_team_panel(on_progress)
                target = self._find_team_by_name(teams, team_name)
                if not target:
                    break

            if not attack_ok:
                # 验证失败不代表没派出 —— compact 列表 OCR 可能漏判。
                # 既然已经点了攻打按钮，假设派兵成功，进入等待阶段。
                # 真的没派出的话，等待阶段会超时结束，不会无限卡。
                if on_progress:
                    on_progress(
                        f"【第{round_no}轮】派兵验证未通过（已重试2次），"
                        f"仍按已派出进入等待：{team_name}")
                attack_ok = True

            attacked_any = True

            # 7. 大地图等待战斗结束
            if on_progress:
                on_progress(f"【第{round_no}轮】等待战斗结果...")
            stopped, final_status = self._wait_battle_return(
                loc, target, on_progress, should_stop)
            if stopped:
                break

        # 保存战败统计
        if defeat_count > 0:
            self.report["defeat_count"] = (
                self.report.get("defeat_count", 0) + defeat_count)

        return attacked_any

    def _open_attack_panel_for_city(
        self,
        loc: "BattleLocation",
        on_progress=None,
        should_stop=None,
    ) -> bool:
        """从大地图导航到城池战事，定位城市，点攻城打开攻打面板。

        返回是否成功打开面板（面板已打开即可，不校验内容）。
        """
        # 从大地图进入情报→城池战事
        if not self._navigate_to_city_war(on_progress):
            return False
        # 定位城市
        if not self._click_city_by_name(loc.name, on_progress):
            return False
        if self._sleep_interruptible(1.0, should_stop):
            return False
        # 点攻城打开队伍面板
        if not self._click_city_action(on_progress):
            return False
        if self._sleep_interruptible(1.5, should_stop):
            return False
        return True

    def _verify_team_marching(self, team_name: str) -> bool:
        """在大地图上通过 compact 队伍列表验证队伍是否出征中。"""
        try:
            teams = self._parse_team_panel(compact=True)
        except Exception:  # noqa: BLE001
            return False
        t = self._find_team_by_name(teams, team_name)
        if not t:
            return False
        status = t.get("status", "") or t.get("name", "")
        return any(
            kw in status for kw in
            ("出征中", "行军中", "前往", "抵达", "●", "剩余", "战斗中")
        )

    def _find_team_by_name(self, teams: list[dict], name: str,
                           fallback: Optional[dict] = None) -> Optional[dict]:
        """按名称在队伍面板中查找队伍。找不到返回 fallback。

        匹配优先级：完全相等 > 包含 > 2字以上共同汉字模糊匹配。
        """
        if not name:
            return fallback
        name_chars = set(c for c in name if '\u4e00' <= c <= '\u9fff')
        # 1. 完全相等
        for t in teams:
            if t.get("name") == name:
                return t
        # 2. 包含
        for t in teams:
            tname = t.get("name", "")
            if name in tname or tname in name:
                return t
        # 3. 模糊匹配：至少 2 个共同汉字
        if len(name_chars) >= 2:
            best_t, best_count = None, 0
            for t in teams:
                tname = t.get("name", "")
                t_chars = set(c for c in tname if '\u4e00' <= c <= '\u9fff')
                common = len(name_chars & t_chars)
                if common >= 2 and common > best_count:
                    best_t = t
                    best_count = common
            if best_t:
                return best_t
        return fallback

    def _parse_injury_wait(self, target: dict) -> int:
        """从队伍状态文本解析重伤恢复倒计时（秒）。读不到则返回 0。"""
        injury_time = target.get("injury_time") or 0
        if injury_time > 0:
            return injury_time
        status = target.get("status") or ""
        m = re.search(r"(\d+)\s*秒", status)
        if m:
            return int(m.group(1))
        m = re.search(r"(\d{1,3}):(\d{2})", status)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
        return 0

    def _has_no_food(self) -> bool:
        """补兵后检查是否出现『粮食不足/无粮食』提示。

        模板匹配优先（`zhan_gong_no_food.png`），OCR 关键词兜底。
        """
        # 模板匹配优先
        if self._template_found("zhan_gong_no_food.png", threshold=0.6):
            return True
        # OCR 兜底：限定在 toast_roi 区域，避免全屏噪音
        return self._has_toast(
            ["粮食不足", "粮草不足", "无粮食", "粮食不够",
             "粮草不够", "没有粮食", "资源不足"])

    def _has_toast(self, keywords: list[str],
                   template: str = "") -> bool:
        """在 toast_roi 区域检测短促提示（如血量不足/无法攻打）。

        模板匹配优先（若给 template），OCR 限定在 toast_roi 小区域兜底，
        避免全屏 OCR 引入 UI 文本噪音。
        """
        if template and self._template_found(template, threshold=0.6):
            return True
        try:
            results = self.ctrl.ocr(roi=self.toast_roi)
            for r in results:
                text = (r.get("text") or "").strip()
                if any(kw in text for kw in keywords):
                    return True
        except Exception as e:  # noqa: BLE001
            logger.debug("toast 检查 OCR 失败: %s", e)
        return False

    def _sleep_interruptible(
        self,
        seconds: float,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """可打断的等待。返回 True 表示停止被请求（应中断当前流程）。"""
        if should_stop is None:
            time.sleep(seconds)
            return False
        end = time.time() + seconds
        while time.time() < end:
            if should_stop():
                return True
            time.sleep(min(0.2, end - time.time()))
        return False

    # ---------------- 队伍面板 ----------------

    # 攻打面板中补兵/攻打按钮相对卡片中心的 x 偏移（横屏 1280x720）
    # 攻打/行军按钮在最右侧，补兵在其左边（图标按钮，OCR读不到文字时用固定坐标）
    # 校准依据：运行日志模板命中攻打按钮实测 (1221,258)；vision 复读
    # MuMu-20260814-025514-633.png 两按钮水平中心距约 70px、补兵按钮中心 x≈1127-1151。
    # 旧值（攻打 1238 / 补兵 1170）整体偏右约 20-40px，导致补兵点击落到
    # 按钮缝隙/攻打按钮上，补兵从未生效（日志：每轮补兵但兵力耗尽→暂无队伍）。
    ATTACK_BTN_DX_FROM_RIGHT = 45  # 卡片右边缘(1260)往左 45px ≈ 1215
    SUPPLY_BTN_DX_FROM_RIGHT = 120  # 卡片右边缘往左 120px ≈ 1140
    # 面板底部『一键补兵』大按钮固定坐标（vision 校准 MuMu-20260814-025514-633.png：
    # x≈615-880、y≈620-670 → 中心 (747,645)）
    SUPPLY_ALL_BTN_COORD = (747, 645)
    # 攻打/补兵按钮相对卡片顶部的 y 偏移（vision 校准 MuMu-20260814-025514-633.png：
    # 第1卡顶部166→攻打按钮218，第2卡292→344，offset 一致为 52px）
    ATTACK_BTN_Y_OFFSET = 52
    # 面板右边缘 x 坐标（横屏）
    PANEL_RIGHT_X = 1260
    # 大地图情报入口按钮固定坐标（依据日志：score=0.91/0.98 时点击 (103,572)）
    INTEL_BTN_COORD = (103, 572)
    # 情报面板左侧「城池战事」页签固定坐标（OCR/模板都失败时兜底）
    # 位置：左侧页签第2个，x≈100-120，y≈200-250（1280x720）
    CITY_WAR_TAB_COORD = (108, 225)
    # 点空白处回到大地图时用的坐标（地图空白区域）
    WORLD_MAP_BLANK = (400, 400)
    # 左上角返回按钮固定坐标（关闭面板/返回上一级）
    BACK_BTN_COORD = (20, 20)

    def _back_to_world_map(self, on_progress=None) -> None:
        """从任意面板/页面返回到大地图。

        策略：先尝试点空白处关面板（城池战事/队伍面板等可以点空白关闭）。
        如果点空白没效果（比如在英雄详情页），则点左上角返回键。
        通过检测是否出现大地图特征（右侧队伍列表含"队"字）来确认。
        """
        # 第一步：连续点空白 3 次，关掉可能存在的浮层
        for _ in range(3):
            self.ctrl.click(self.WORLD_MAP_BLANK[0], self.WORLD_MAP_BLANK[1])
            time.sleep(self.wait_anim)

        # 第二步：检测是否在大地图（右侧队伍区域含"队"字）
        if self._is_on_world_map():
            if on_progress:
                on_progress("已回到大地图")
            return

        # 第三步：点左上角返回，最多 5 次，直到回到大地图
        for _ in range(5):
            self.ctrl.click(self.BACK_BTN_COORD[0], self.BACK_BTN_COORD[1])
            time.sleep(self.wait_anim + 0.3)
            if self._is_on_world_map():
                if on_progress:
                    on_progress("已回到大地图")
                return

        # 最后兜底：再点几次空白
        for _ in range(3):
            self.ctrl.click(self.WORLD_MAP_BLANK[0], self.WORLD_MAP_BLANK[1])
            time.sleep(self.wait_anim)

        if on_progress:
            on_progress("已回到大地图（兜底）")

    def _is_on_world_map(self) -> bool:
        """检测是否在大地图：右侧队伍区域含'队'字样。"""
        try:
            # 右侧队伍列表区域：x≈1080-1260, y≈200-500
            results = self.ctrl.ocr((1080, 200, 180, 300))
            for r in results:
                text = (r.get("text") or "").strip()
                if "队" in text and len(text) >= 2:
                    return True
        except Exception as e:  # noqa: BLE001
            logger.debug("is_on_world_map OCR 失败: %s", e)
        return False

    def _parse_team_panel(self, on_progress=None,
                          compact: bool = False) -> list[dict]:
        """解析右侧队伍面板，返回队伍列表。

        compact=False（默认）：攻城队伍卡片，每张约 130px 高，含 3 行（耗时/队名/战力状态）。
        compact=True：大地图常驻队伍列表，每行约 75px 高，含 2 行（位置/队名）。

        每个队伍字典：
        {
            "name": "马超队",
            "power": 62574,
            "status": "驻守中",
            "cost_time": 218,
            "attackable": True,
            "attack_btn": (x, y),
            "supply_btn": (x, y),
            "row_y": 120,
            "need_supply": False,
        }
        """
        try:
            results = self.ctrl.ocr(roi=self.team_panel_roi)
        except Exception as e:  # noqa: BLE001
            logger.warning("队伍面板 OCR 失败: %s", e)
            return []

        items = []
        for r in results:
            text = (r.get("text") or "").strip()
            if not text:
                continue
            box = r.get("box", (0, 0, 0, 0))
            items.append({"text": text, "x": box[0], "y": box[1],
                          "w": box[2], "h": box[3]})

        items.sort(key=lambda it: it["y"])

        logger.debug("队伍面板 OCR raw (%d): %s", len(items),
                     [(it["text"], it["x"], it["y"], it["w"], it["h"])
                      for it in items])

        # 按卡片分组：紧凑模式行高更小，避免两支队伍合并
        card_h = 75 if compact else 130
        cards = self._group_into_cards(items, card_height=card_h)
        logger.debug("队伍面板 %d 张卡片: %s", len(cards),
                     [[it["text"] for it in card] for card in cards])

        teams = []
        for card in cards:
            team = self._parse_team_card(card)
            if team:
                teams.append(team)

        # 重伤队伍队名为空时（重伤时队名被倒计时覆盖），用序号填充占位名
        # 确保队伍计数/序号正确，避免"邺城"等地点名被误作队名
        for idx, team in enumerate(teams, 1):
            if team.get("is_injured") and not team.get("name"):
                team["name"] = f"第{idx}队重伤中"

        # 血条检测：有兵=绿色，无兵=灰色 → 需要补兵
        self._mark_need_supply(teams, compact=compact)
        return teams

    def _group_into_cards(self, items: list[dict],
                          card_height: int = 130) -> list[list[dict]]:
        """把按 y 排序的 OCR 条目按卡片分组。

        策略：每张卡片顶部 y 为锚，下一张卡片的顶部 = 上一张卡片顶部 + card_height。
        当新条目的 y 比当前卡片顶部高出 card_height * 0.7 以上时，视为新卡片。
        """
        cards: list[list[dict]] = []
        for it in items:
            placed = False
            for card in cards:
                top = min(i["y"] for i in card)
                if it["y"] - top < card_height * 0.7:
                    card.append(it)
                    placed = True
                    break
            if not placed:
                cards.append([it])
        return cards

    def _mark_need_supply(self, teams: list[dict], compact: bool = False) -> None:
        """用屏色判断每支队伍血条颜色：绿=有兵，灰/暗=无兵需补兵。

        攻城面板（compact=False）：血条位于每张卡片左侧武将头像底部，
        横屏 1280x720 下头像 x≈615-675，血条纵向约在卡片顶部下方 85-105px
        （vision 校准 MuMu-20260814-025514-633.png：第1卡顶部152→血条≈237-247）。
        旧逻辑用 row_y（OCR条目中心均值，偏高约 35px）取样，命中头像而非血条，
        导致恒判"需补兵"。

        compact=True（大地图列表）：布局不同且不参与补兵判定，跳过检测。
        """
        if compact:
            for team in teams:
                team["need_supply"] = False
            return
        if not teams:
            return
        try:
            img = self.ctrl.screencap()
        except Exception as e:  # noqa: BLE001
            logger.debug("截屏检测血条失败: %s", e)
            return
        w, h = img.size
        for team in teams:
            top = team.get("card_top", 0) or team.get("row_y", 0)
            if top <= 0:
                continue
            # 头像底部血条：x≈600-680，y≈card_top+75..card_top+105
            bar_y0 = max(0, top + 75)
            bar_y1 = min(h - 1, top + 105)
            green = False
            for y in range(bar_y0, bar_y1 + 1):
                for x in range(600, 681, 2):
                    if x >= w:
                        continue
                    try:
                        r, g, b = img.getpixel((x, y))[:3]
                    except Exception:  # noqa: BLE001
                        continue
                    if self._is_green(r, g, b):
                        green = True
                        break
                if green:
                    break
            team["need_supply"] = not green
        return

    @staticmethod
    def _is_green(r: int, g: int, b: int) -> bool:
        """判断是否为绿血条像素（RGB(62,203,98) 附近）。"""
        return g > 120 and g > r * 1.6 and g > b * 1.6

    def read_my_teams(self, on_progress=None) -> list[dict]:
        """读取大地图右侧常驻队伍列表，返回队伍字典列表。

        大地图队伍列表是紧凑布局（每行约 75px，2 行文字），使用 compact 模式解析。
        """
        try:
            teams = self._parse_team_panel(on_progress, compact=True)
            if on_progress:
                names = [t.get("name", "?") for t in teams]
                on_progress(f"读取到 {len(teams)} 支队伍：{'、'.join(names)}")
            return teams
        except Exception as e:  # noqa: BLE001
            logger.exception("读取队伍列表失败")
            if on_progress:
                on_progress(f"读取队伍列表失败：{e}")
            return []

    def _parse_team_card(self, card: list[dict]) -> Optional[dict]:
        """从一张卡片（多行 OCR 条目）解析一个队伍。"""
        if not card:
            return None

        # 卡片顶部 y（攻打/补兵按钮在卡片下部，用顶部+固定偏移更稳）
        card_top = min(it["y"] for it in card)
        # 卡片中心 y（备用）
        ys = [it["y"] + it["h"] // 2 for it in card]
        card_y = sum(ys) // len(ys)

        all_text = " ".join(it["text"] for it in card)

        # 重伤检测：卡片含"重伤"字样 + 倒计时格式（X分X秒）→ 重伤队伍
        # 重伤时队名区显示地点名+倒计时（如"邺城"+"2分16秒"），队名被覆盖
        is_injured = any("重伤" in it["text"] for it in card)
        injury_time = 0
        if is_injured:
            for it in card:
                t = it["text"]
                if re.search(r"\d+分\d+秒", t) or re.search(r"\d+[:：]\d+", t):
                    injury_time = self._parse_time_text(t)
                    if injury_time > 0:
                        break

        def _is_noise(t: str) -> bool:
            t = t.strip()
            # 直接命中噪音词表 → 噪音
            if t in self.TEAM_NAME_NOISE:
                return True
            # 状态词 → 噪音
            if t in self.TEAM_STATUS_NOISE:
                return True
            # 含"队"但"队"前是页签/UI词（我的/临时/剩余等）或非纯人名 → 噪音
            if "队" in t:
                before = t[:t.find("队")]
                if before in self.TEAM_NAME_PREFIX_NOISE:
                    return True
                # 被抓取的队名必须能形成"X队"（X为2-3字人名）
                return not re.fullmatch(r"[\u4e00-\u9fa5]{2,3}", before)
            # 其他不含"队"的短文本：看是否在噪音词表/是否像人名
            return len(t) <= 1 or t in self.TEAM_NAME_NOISE

        # 找队伍名：优先取含"队"字且非噪音的条目
        # 队名特征："队"字前面是人名（至少1个汉字），不是纯数字/分数/UI文本
        # 支持 OCR 拆分："高顺"+"队" 两条目拼成 "高顺队"
        name = ""
        for it in card:
            t = it["text"]
            if "队" in t and len(t) <= 8 and not _is_noise(t):
                before_dui = t[:t.find("队")]
                # 队名前必须是纯汉字人名（含合法符号的直接排除，如"[组队"）
                if re.fullmatch(r"[\u4e00-\u9fa5]+", before_dui):
                    name = t
                    break
        if not name:
            # "队"被 OCR 拆成独立条目：往前找紧邻的 2-3 字人名拼成 "X队"
            for i, it in enumerate(card):
                t = it["text"]
                if t == "队" or (t.startswith("队") and len(t) <= 3):
                    # 往回找紧邻的纯汉字人名条目
                    for j in range(i - 1, -1, -1):
                        prev = card[j]["text"].strip()
                        if re.fullmatch(r"[\u4e00-\u9fa5]{2,3}", prev):
                            name = prev + "队"
                            break
                    if name:
                        break
        if not name and not any("队" in it["text"] for it in card):
            # 完全没有"队"字条目：只接受 3 字以上纯中文人名（避免"邺城"等2字地点）
            for it in card:
                t = it["text"]
                if re.fullmatch(r"[\u4e00-\u9fa5]{3,4}", t) and not _is_noise(t):
                    name = t
                    break
        if not name:
            # 没有明显"队"字：找战力数字左边的中文名字（要求 3 字以上，避免"邺城"等地名）
            sorted_by_x = sorted(card, key=lambda it: it["x"])
            for i, it in enumerate(sorted_by_x):
                if re.match(r"^\d{4,6}$", it["text"]):
                    if i > 0:
                        cand = sorted_by_x[i - 1]["text"]
                        if re.fullmatch(r"[\u4e00-\u9fa5]{3,4}", cand) and not _is_noise(cand):
                            name = cand
                    break
        if not name:
            has_status = any(
                kw in all_text
                for kw in ("驻守中", "备战中", "伤兵", "重伤", "出征中",
                           "行军中", "恢复中", "在野", "城内", "驻守", "防守")
            )
            if has_status:
                for it in card:
                    t = it["text"]
                    if (re.fullmatch(r"[\u4e00-\u9fa5]{3,4}", t)
                            and not _is_noise(t)):
                        name = t
                        break
        if not name:
            if is_injured:
                name = ""
            else:
                return None

        # 最终硬校验：排除 UI 噪音文本被误认为队伍名
        # - 含"队"：队前必须是 2-3 字纯汉字人名（拒绝"组队""队伍""剩余队""我的队"等）
        # - 不含"队"：须为 2-3 字纯汉字且非噪音（可能是队名被 OCR 截断，如"蔡文姬"）
        # - 重伤队伍且队名为空：跳过校验（重伤时队名被倒计时覆盖，读不到真名）
        name_clean = name.strip()
        if name_clean:
            if name_clean in self.TEAM_NAME_NOISE:
                return None
            if name_clean in self.TEAM_STATUS_NOISE:
                return None
            if "队" in name_clean:
                before_dui = name_clean[:name_clean.find("队")]
                if before_dui in self.TEAM_NAME_PREFIX_NOISE:
                    return None
                if not re.fullmatch(r"[\u4e00-\u9fa5]{2,3}", before_dui):
                    return None
            else:
                if not re.fullmatch(r"[\u4e00-\u9fa5]{2,3}", name_clean):
                    return None
        name = name_clean

        # 清理队名：若"队"字后还有多余字符（如行军目的地），截到"队"为止
        idx_dui = name.find("队")
        if idx_dui >= 0 and idx_dui < len(name) - 1:
            name = name[:idx_dui + 1]

        team = {
            "name": name,
            "power": 0,
            "status": "",
            "cost_time": 0,
            "injury_time": injury_time,
            "attackable": not is_injured,
            "attack_btn": None,
            "supply_btn": None,
            "row_y": card_y,
            "card_top": card_top,
            "need_supply": False,
            "is_injured": is_injured,
        }

        # 战力（4-6 位数字，带钻石图标）
        for it in card:
            t = it["text"].replace(",", "").replace("，", "")
            if re.match(r"^\d{4,6}$", t):
                team["power"] = int(t)
                break

        # 状态：驻守中 / 重伤 / 重伤XX秒 / 恢复中等
        # 注意：必须遍历所有条目，不能第一个命中就 break——
        # 若"驻守中"先出现而"重伤XX秒"后出现，会漏判重伤。
        status_keywords = ["驻守中", "重伤", "恢复中", "行军中", "出征中",
                           "在野", "城内"]
        for it in card:
            t = it["text"]
            for kw in status_keywords:
                if kw in t:
                    # 重伤/恢复中优先级最高，覆盖之前的状态
                    if kw in ("重伤", "恢复中"):
                        team["status"] = t
                        team["attackable"] = False
                    elif not team["status"]:
                        team["status"] = t
                    break

        # 耗时：预计耗时：3分10秒 / 预计耗时: 00:03:10
        # 注意：重伤队伍的 X分X秒 倒计时是恢复时间，不是行军耗时
        cost = 0
        for it in card:
            t = it["text"]
            if "耗时" in t:
                cost = self._parse_time_text(t)
                if cost > 0:
                    break
        if cost == 0 and not is_injured:
            for it in card:
                t = it["text"]
                if re.search(r"\d+分\d+秒", t) or re.search(r"\d+[:：]\d+", t):
                    cost = self._parse_time_text(t)
                    if cost > 0:
                        break
        team["cost_time"] = cost

        # 攻打/补兵按钮：图标按钮，OCR 无文字，用固定 x 坐标 + 卡片中部偏下 y
        # 依据 vision 校准（MuMu-20260814-025514-633.png）：攻打按钮在卡片顶部下方约 66px
        # （第一张卡顶部155 → 攻打按钮221），比卡片中心更可靠
        btn_y = card_top + self.ATTACK_BTN_Y_OFFSET
        team["attack_btn"] = (self.PANEL_RIGHT_X - self.ATTACK_BTN_DX_FROM_RIGHT, btn_y)
        team["supply_btn"] = (self.PANEL_RIGHT_X - self.SUPPLY_BTN_DX_FROM_RIGHT, btn_y)

        return team

    def _find_target_team(self, teams: list[dict], on_progress=None) -> Optional[dict]:
        """在队伍列表里找到目标队伍。优先按名称，失败则按序号。"""
        # 按名称匹配
        if self.team_name:
            for idx, t in enumerate(teams, 1):
                if self.team_name in t["name"] or t["name"] in self.team_name:
                    t["index"] = idx
                    if on_progress:
                        on_progress(f"匹配队伍：{t['name']}")
                    return t
            # 尝试模糊匹配（包含部分文字）
            for idx, t in enumerate(teams, 1):
                if any(c in t["name"] for c in self.team_name if '\u4e00' <= c <= '\u9fff'):
                    t["index"] = idx
                    if on_progress:
                        on_progress(f"模糊匹配队伍：{t['name']}")
                    return t
            if on_progress:
                on_progress(f"未找到名称匹配的队伍『{self.team_name}』，改用第 {self.team_index} 队")

        # 按序号
        if 1 <= self.team_index <= len(teams):
            t = teams[self.team_index - 1]
            t["index"] = self.team_index
            if on_progress:
                on_progress(f"选择第 {self.team_index} 队：{t['name']}")
            return t

        return None

    def _click_city_action(self, on_progress=None) -> bool:
        """点击地点后，识别行动菜单上的『攻城/行军』按钮并点击。

        真实交互：点击城池战事里的战斗地点 → 弹出该城池的**行动菜单**，
        菜单按钮因城池状态而异：可攻打时显示「攻城」，出兵/行军状态显示「行军」。
        点攻城/行军后，右侧才出现队伍选择面板。
        返回是否成功点击了攻城/行军。

        依据截图 zhan_gong_city_menu.png：行动菜单含 攻城/观战/信息/标记 四个按钮，
        攻城按钮在菜单最上方（可攻打状态）。
        """
        if on_progress:
            on_progress("[行动菜单] 检测城池行动菜单，识别攻城/行军按钮...")
        # 收窄 OCR 到行动菜单区域，避免全屏 OCR 读主世界海量文本
        # 依据截图 zhan_gong_city_menu.png：行动菜单在屏幕中上部，
        # 攻城按钮中心约 (880,263)，四按钮纵向分布在 y≈238-468
        menu_roi = (740, 230, 300, 250)
        for attempt in range(3):
            try:
                results = self.ctrl.ocr(roi=menu_roi)
            except Exception as e:  # noqa: BLE001
                logger.debug("行动菜单 OCR 失败: %s", e)
                break
            if on_progress:
                texts = [r.get("text", "") for r in results]
                on_progress(f"[行动菜单] 菜单OCR读到: {texts}")
            for r in results:
                text = (r.get("text") or "").strip()
                # 只点攻城，跳过行军（己方城池）。
                # OCR 敌我数字解析可能不准，以行动菜单上是否有「攻城」为准。
                for kw in ("攻城", "攻打"):
                    if kw in text and "行军" not in text:
                        box = r.get("box", (0, 0, 0, 0))
                        cx = box[0] + box[2] // 2
                        cy = box[1] + box[3] // 2
                        self.ctrl.click(cx, cy)
                        if on_progress:
                            on_progress(f"[行动菜单] 点击了『{kw}』({cx},{cy})")
                        return True
            if on_progress:
                on_progress(f"[行动菜单] 未找到攻城/行军，重试 {attempt + 1}/3")
            time.sleep(1.0)
        return False

    def _click_attack_btn_on_team(self, team: dict,
                                  on_progress=None) -> bool:
        """点击指定队伍的攻打/行军按钮。

        按钮可能是「攻打」图标按钮，也可能随出兵状态变成「行军」。
        优先用 OCR 在卡片行高区域内找「攻打」或「行军」文字点击；
        找不到再用固定坐标点击攻打按钮位置。
        返回是否点击成功。
        """
        ry = team.get("row_y", 0)
        btn_y = ry
        if team.get("attack_btn"):
            btn_y = team["attack_btn"][1]
        if on_progress:
            on_progress(f"[攻打] 菜单已弹出，识别攻打/行军按钮（行y={btn_y}）...")

        # OCR 区域：覆盖卡片右侧按钮区（补兵+攻打），中心放在按钮行（btn_y）
        # 旧逻辑以 ry（OCR条目中心均值）为锚，偏高约 35px，读不到按钮下方文字
        roi = (self.PANEL_RIGHT_X - 300, btn_y - 40, 320, 100)
        if on_progress:
            on_progress(f"[攻打] OCR区域={roi}")
        try:
            results = self.ctrl.ocr(roi=roi)
            if on_progress:
                texts = [r.get("text", "") for r in results]
                on_progress(f"[攻打] OCR读到: {texts}")
            for r in results:
                text = (r.get("text") or "").strip()
                for kw in ("行军", "攻打", "出征", "前往"):
                    if kw in text:
                        box = r.get("box", (0, 0, 0, 0))
                        cx = box[0] + box[2] // 2
                        cy = box[1] + box[3] // 2
                        self.ctrl.click(cx, cy)
                        if on_progress:
                            on_progress(f"[攻打] 通过OCR点击了『{kw}』({cx},{cy})")
                        return True
        except Exception as e:  # noqa: BLE001
            logger.debug("攻打按钮 OCR 失败: %s", e)
            if on_progress:
                on_progress(f"[攻打] OCR异常: {e}")

        # 2) 模板匹配攻打按钮图标（zhan_gong_confirm_btn.png 实为攻打按钮）
        if self._click_template(
            "zhan_gong_confirm_btn.png",
            threshold=0.6,
            max_retries=2,
            wait_after=0.5,
            on_progress=on_progress,
            desc="攻打按钮模板",
        ):
            return True

        # 3) 固定坐标兜底（攻打图标按钮）
        if team.get("attack_btn"):
            x, y = team["attack_btn"]
            self.ctrl.click(x, y)
            if on_progress:
                on_progress(f"[攻打] OCR未找到文字，固定坐标点攻打 ({x},{y})")
            return True
        # 3) 最后兜底：在行高度上点右侧区域
        fx, fy = self.PANEL_RIGHT_X - 45, ry
        self.ctrl.click(fx, fy)
        if on_progress:
            on_progress(f"[攻打] 兜底点右侧 ({fx},{fy})")
        return True

    def _click_supply_btn(self, team: dict, on_progress=None) -> bool:
        """点击指定队伍的补兵按钮。返回是否点击了。

        优先 OCR 在按钮行区域找『补兵』文字点击（图标下方有文字标签）；
        找不到再用固定坐标点击补兵按钮位置。
        """
        ry = team.get("row_y", 0)
        btn_y = ry
        if team.get("supply_btn"):
            btn_y = team["supply_btn"][1]
        elif team.get("attack_btn"):
            btn_y = team["attack_btn"][1]

        # OCR 区域：覆盖该行按钮区（图标+下方文字），中心放在按钮行上
        if btn_y > 0:
            roi = (self.PANEL_RIGHT_X - 300, btn_y - 40, 320, 100)
            try:
                results = self.ctrl.ocr(roi=roi)
                for r in results:
                    text = (r.get("text") or "").strip()
                    if "补兵" in text:
                        box = r.get("box", (0, 0, 0, 0))
                        cx = box[0] + box[2] // 2
                        cy = box[1] + box[3] // 2
                        self.ctrl.click(cx, cy)
                        if on_progress:
                            on_progress(f"[补兵] OCR点击『补兵』({cx},{cy})")
                        return True
            except Exception as e:  # noqa: BLE001
                logger.debug("补兵按钮 OCR 失败: %s", e)

        if team.get("supply_btn"):
            x, y = team["supply_btn"]
            self.ctrl.click(x, y)
            if on_progress:
                on_progress(f"[补兵] 固定坐标点补兵 ({x},{y})")
            return True
        # 兜底：攻打按钮左侧
        if team.get("attack_btn"):
            ax, ay = team["attack_btn"]
            self.ctrl.click(ax - 80, ay)
            return True
        return False

    def _click_supply_all_btn(self, on_progress=None) -> bool:
        """点击队伍面板底部的『一键补兵』大按钮（给全部队伍补兵）。

        OCR 在按钮区域找『一键补兵』文字优先；找不到用固定坐标兜底。
        """
        # OCR 区域：面板底部『一键补兵』『一键前往』两枚大按钮所在行
        try:
            roi = (600, 600, 680, 100)
            results = self.ctrl.ocr(roi=roi)
            for r in results:
                text = (r.get("text") or "").strip()
                if "一键补兵" in text:
                    box = r.get("box", (0, 0, 0, 0))
                    cx = box[0] + box[2] // 2
                    cy = box[1] + box[3] // 2
                    self.ctrl.click(cx, cy)
                    if on_progress:
                        on_progress(f"[补兵] OCR点击『一键补兵』({cx},{cy})")
                    return True
        except Exception as e:  # noqa: BLE001
            logger.debug("一键补兵按钮 OCR 失败: %s", e)

        # 固定坐标兜底（vision 校准 MuMu-20260814-025514-633.png：
        # 『一键补兵』x≈615-880、y≈620-670 → 中心 (747,645)）
        x, y = self.SUPPLY_ALL_BTN_COORD
        self.ctrl.click(x, y)
        if on_progress:
            on_progress(f"[补兵] 固定坐标点『一键补兵』({x},{y})")
        return True

    def _close_team_panel(self) -> None:
        """关闭右侧队伍面板（点一下地图空白区域或X）。"""
        try:
            # 点面板外地图区域
            self.ctrl.click(400, 400)
            time.sleep(self.wait_anim)
        except Exception as e:  # noqa: BLE001
            logger.debug("关闭面板失败: %s", e)

    @staticmethod
    def _parse_time_text(text: str) -> int:
        """从文本里解析时间（秒）。支持：
        - 3分38秒 → 218
        - 00:03:38 → 218
        - 3:38 → 218
        - 200秒 → 200
        """
        text = text.strip()
        # 3分38秒
        m = re.search(r"(\d+)\s*分\s*(\d+)\s*秒", text)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
        # 3分
        m = re.search(r"(\d+)\s*分", text)
        if m:
            return int(m.group(1)) * 60
        # 00:03:38
        m = re.search(r"(\d{1,2})[:：](\d{2})[:：](\d{2})", text)
        if m:
            h, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return h * 3600 + mm * 60 + ss
        # 3:38
        m = re.search(r"(\d{1,2})[:：](\d{2})", text)
        if m:
            mm, ss = int(m.group(1)), int(m.group(2))
            return mm * 60 + ss
        # 200秒
        m = re.search(r"(\d+)\s*秒", text)
        if m:
            return int(m.group(1))
        return 0

    def _confirm_attack(self, on_progress=None) -> bool:
        """确认出征（如果有确认弹窗的话）。返回是否点到了确认。"""
        # 模板匹配
        if self._click_template(
            "zhan_gong_confirm_btn.png",
            threshold=0.6,
            max_retries=2,
            wait_after=self.wait_anim,
            on_progress=on_progress,
            desc="确认出征按钮",
        ):
            return True

        # OCR 兜底
        for kw in ("立即出征", "出征", "确认出征", "确认", "派兵", "确定"):
            if self._click_text(kw, max_retries=1, wait_after=self.wait_anim):
                if on_progress:
                    on_progress(f"通过 OCR 点击了『{kw}』")
                return True

        # 检查是否有不可攻打提示（模板优先，OCR 兜底）
        if self._template_found("zhan_gong_unavailable.png", threshold=0.6):
            if on_progress:
                on_progress("检测到不可攻打提示（模板）")
            return False
        try:
            results = self.ctrl.ocr()
            for r in results:
                text = (r.get("text") or "").strip()
                if any(kw in text for kw in self.UNAVAILABLE_KEYWORDS):
                    if on_progress:
                        on_progress(f"检测到不可攻打提示：{text[:20]}")
                    return False
        except Exception as e:  # noqa: BLE001
            logger.debug("不可攻打检查 OCR 失败: %s", e)
        # 没有确认弹窗也可能是正常的（直接出兵了）
        return False

    def _cancel_attack(self) -> None:
        """取消攻打（关闭弹窗/面板）。"""
        self._close_team_panel()


    def _wait_battle_end(
        self,
        on_progress: Optional[Callable[[str], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """等待战斗结束（固定等待 + 轮询判断结果弹窗）。

        返回 True 表示停止被请求（应中断整个攻打流程）。
        """
        # 战斗动画 + 结算，先固定等待
        if self._sleep_interruptible(3.0, should_stop):
            return True
        # 轮询一段时间，直到出现结果弹窗或超时
        deadline = time.time() + 60
        while time.time() < deadline:
            if should_stop and should_stop():
                return True
            if self._has_result_popup():
                return False
            time.sleep(1.0)
        if on_progress:
            on_progress("等待战斗结果超时，继续")
        return False

    def _wait_battle_return(
        self,
        loc: BattleLocation,
        target: dict,
        on_progress=None,
        should_stop=None,
    ) -> tuple[bool, str]:
        """派兵后等待战斗结束并回城，期间检测并关闭战败弹窗。

        通过大地图右侧常驻队伍列表（compact模式）轮询队伍状态，
        因为攻打面板内的预计时间是静态的，不会实时更新。

        返回 (stopped, status)：
          - stopped=True 表示被停止请求中断
          - status 为最终检测到的队伍状态字符串
        """
        team_name = target.get("name", "?")
        cost = max(loc.cost_time, 60)
        total_timeout = cost * 2 + 300
        deadline = time.time() + total_timeout
        poll_interval = 15

        if on_progress:
            on_progress(
                f"等待战斗结束（预计最长 {total_timeout} 秒，"
                f"行军 {cost}s + 战斗缓冲）")

        # 确保在大地图（compact 队伍列表在大地图才实时更新）
        self._back_to_world_map(on_progress)
        if self._sleep_interruptible(2.0, should_stop):
            return True, "?"

        last_status = "出征中"
        while time.time() < deadline:
            if should_stop and should_stop():
                return True, last_status

            # 1. 优先检测战败弹窗
            if self._has_result_popup():
                self._dismiss_result()
                if on_progress:
                    on_progress("检测到战败弹窗，已关闭")
                if self._sleep_interruptible(3.0, should_stop):
                    return True, "战败"
                continue

            # 2. 用大地图常驻队伍列表（compact）检测状态
            try:
                teams = self._parse_team_panel(compact=True)
            except Exception as e:  # noqa: BLE001
                logger.debug("等待战斗中队伍列表解析失败: %s", e)
                teams = []

            if teams:
                t = self._find_team_by_name(teams, team_name, target)
                if t:
                    status = t.get("status", "") or t.get("name", "")
                    # 出征中的关键词
                    if any(kw in status for kw in
                           ("出征中", "行军中", "前往", "抵达",
                            "●", "剩余", "战斗中")):
                        last_status = status
                    else:
                        # 不再是出征状态 → 战斗结束，队伍已回城/重伤
                        if on_progress:
                            on_progress(
                                f"战斗结束，队伍『{team_name}』"
                                f"状态：{status or '正常'}")
                        return False, status

            # 3. 继续等待
            if self._sleep_interruptible(poll_interval, should_stop):
                return True, last_status

        if on_progress:
            on_progress(
                f"等待战斗结束超时（{total_timeout}s），"
                f"队伍『{team_name}』状态：{last_status}")
        return False, "超时"

    def _wait_battle_return_multi(
        self,
        loc: BattleLocation,
        targets: list[dict],
        on_progress=None,
        should_stop=None,
    ) -> bool:
        """批量派兵后，一起等待所有队伍的后续战斗结束并回城。

        通过大地图右侧常驻队伍列表（compact）轮询各队伍状态，
        与 _wait_battle_return 单队伍逻辑等价的批量版本：
        任一战败弹窗都关闭；某队不再处于出征状态即视为该队战斗结束；
        所有队伍都结束（或不在列表/超时）后返回。

        返回 stopped：True 表示被停止请求中断。
        """
        if not targets:
            return False
        cost = max(loc.cost_time, 60)
        total_timeout = cost * 2 + 300
        deadline = time.time() + total_timeout
        poll_interval = 15

        # 记录尚在等待的队伍名称；每队一旦结束就从 pending 中移除
        pending = [t.get("name", "?") for t in targets]
        if on_progress:
            on_progress(
                f"等待 {len(pending)} 支队伍战斗结束"
                f"（预计最长 {total_timeout} 秒，行军 {cost}s + 战斗缓冲）")

        while time.time() < deadline and pending:
            if should_stop and should_stop():
                return True

            # 1. 战败弹窗：批量时任一队伍失败都会弹，关闭即可
            if self._has_result_popup():
                self._dismiss_result()
                if on_progress:
                    on_progress("检测到战败弹窗，已关闭")
                if self._sleep_interruptible(3.0, should_stop):
                    return True
                continue

            # 2. 用大地图常驻队伍列表（compact）检测各队状态
            try:
                teams = self._parse_team_panel(compact=True)
            except Exception as e:  # noqa: BLE001
                logger.debug("等待战斗中队伍列表解析失败: %s", e)
                teams = []

            if teams:
                done = []
                for name in pending:
                    t = self._find_team_by_name(teams, name)
                    if not t:
                        # 列表里找不到该队：可能已结束不在列表，视为完成
                        done.append(name)
                        continue
                    status = t.get("status", "") or t.get("name", "")
                    # 出征中的关键词
                    if any(kw in status for kw in
                           ("出征中", "行军中", "前往", "抵达",
                            "●", "剩余", "战斗中")):
                        continue
                    # 不再是出征状态 → 该队战斗结束，队伍已回城/重伤
                    done.append(name)
                    if on_progress:
                        on_progress(
                            f"战斗结束，队伍『{name}』"
                            f"状态：{status or '正常'}")
                for name in done:
                    if name in pending:
                        pending.remove(name)
                if not pending:
                    if on_progress:
                        on_progress("所有队伍战斗均已结束")
                    return False

            # 3. 继续等待
            if self._sleep_interruptible(poll_interval, should_stop):
                return True

        if pending and on_progress:
            on_progress(
                f"等待战斗结束超时（{total_timeout}s），"
                f"尚未结束的队伍：{pending}")
        return False

    def _has_result_popup(self) -> bool:
        """判断是否出现战斗结果弹窗（战败/重伤救治提示）。

        模板匹配优先（`zhan_gong_defeat.png`），OCR 关键词兜底。
        注意：本游戏没有胜利弹窗，只有战败弹窗（提示队伍重伤、需粮草救治）。
        """
        # 模板匹配优先
        if self._template_found("zhan_gong_defeat.png", threshold=0.6):
            return True
        # OCR 兜底
        try:
            results = self.ctrl.ocr()
            for r in results:
                text = (r.get("text") or "").strip()
                for kw in ("胜利", "战败", "战败回城", "撤离", "战斗结束"):
                    if kw in text:
                        return True
        except Exception as e:  # noqa: BLE001
            logger.debug("结果弹窗判定失败: %s", e)
        return False

    def _dismiss_result(self) -> None:
        """关闭战败弹窗（返还粮草提示）。

        逻辑：先点左下角勾选框『今日不再提示』，再点右下角『确认』。
        用模板匹配定位弹窗位置，按模板图内坐标换算勾选框/确认按钮位置；
        模板匹配不到时，OCR 找『确认』文字兜底。
        """
        # 模板图内坐标（zhan_gong_defeat.png 779x289）
        #   勾选框中心约 (57, 244)，确认按钮中心约 (642, 240)
        tpl_w, tpl_h = 779, 289
        try:
            boxes = self.ctrl.recognize("zhan_gong_defeat.png", 0.6)
            if boxes:
                x, y, w, h, _ = boxes[0]
                sx, sy = w / tpl_w, h / tpl_h
                # 先点左下角勾选框
                cbx, cby = x + 57 * sx, y + 244 * sy
                self.ctrl.click(round(cbx), round(cby))
                time.sleep(self.wait_anim)
                # 再点右下角确认
                okx, oky = x + 642 * sx, y + 240 * sy
                self.ctrl.click(round(okx), round(oky))
                time.sleep(self.wait_anim)
                return
        except Exception as e:  # noqa: BLE001
            logger.debug("弹窗模板定位失败: %s", e)
        # OCR 兜底：点『确认』
        try:
            self._click_text("确认", max_retries=2, wait_after=self.wait_anim)
        except Exception as e:  # noqa: BLE001
            logger.debug("关闭结果 OCR 失败: %s", e)

    # ---------------- 报告 ----------------

    def _loc_to_report(self, loc: BattleLocation, attacked: bool = False) -> dict:
        return {
            "name": loc.name,
            "x": loc.x,
            "y": loc.y,
            "my_troops": loc.my_troops,
            "enemy_troops": loc.enemy_troops,
            "cost_time": loc.cost_time,
            "attackable": loc.attackable,
            "skip_reason": loc.skip_reason,
            "score": round(loc.score, 2),
            "attacked": attacked,
        }

    def save_report(self, path: str | Path | None = None) -> str:
        """保存诊断报告为 JSON，返回文件路径。"""
        from app.utils.logger import LOG_DIR
        out_dir = Path(path) if path else LOG_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fpath = out_dir / f"zhan_gong_{ts}.json"
        fpath.write_text(
            json.dumps(self.report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("ZhanGong report saved: %s", fpath)
        return str(fpath)