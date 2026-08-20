"""战功引擎门面（薄）：聚合编排，不含新业务逻辑。

对外契约（与旧 app/core/zhan_gong_engine.py 保持一致）：
  - ZhanGongEngine(ctrl, params) 可构造
  - .run(on_progress, should_stop) -> dict
  - .read_my_teams(on_progress) -> list[dict]
  - .save_report(path=None) -> str

实现已按功能拆分到本包各模块；此处仅保留参数装配与跨模块编排（纯移动，无改动）。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import constants
from . import report as report_mod
from . import scoring
from . import list_reader
from . import navigation
from . import attack
from . import team_panel
from .. import config as zg_config
from .selection import TargetSelector
from .model import BattleLocation  # noqa: F401  (re-export)


class ZhanGongEngine:
    """战功自动攻城引擎（纯逻辑门面）。"""

    # ---- 类级常量（原样搬运自旧模块，保持外部可访问） ----
    UNAVAILABLE_KEYWORDS = constants.UNAVAILABLE_KEYWORDS
    TEAM_NAME_NOISE = constants.TEAM_NAME_NOISE
    TEAM_NAME_PREFIX_NOISE = constants.TEAM_NAME_PREFIX_NOISE
    TEAM_STATUS_NOISE = constants.TEAM_STATUS_NOISE
    LOCATION_NAME_NOISE = constants.LOCATION_NAME_NOISE
    LOCATION_MIN_CHINESE = constants.LOCATION_MIN_CHINESE
    HEADER_KEYWORDS = constants.HEADER_KEYWORDS
    ENEMY_PREFIXES = constants.ENEMY_PREFIXES
    ATTACK_BTN_DX_FROM_RIGHT = constants.ATTACK_BTN_DX_FROM_RIGHT
    SUPPLY_BTN_DX_FROM_RIGHT = constants.SUPPLY_BTN_DX_FROM_RIGHT
    ATTACK_BTN_Y_OFFSET = constants.ATTACK_BTN_Y_OFFSET
    PANEL_RIGHT_X = constants.PANEL_RIGHT_X
    SUPPLY_ALL_BTN_COORD = constants.SUPPLY_ALL_BTN_COORD
    INTEL_BTN_COORD = constants.INTEL_BTN_COORD
    CITY_WAR_TAB_COORD = constants.CITY_WAR_TAB_COORD
    WORLD_MAP_BLANK = constants.WORLD_MAP_BLANK
    BACK_BTN_COORD = constants.BACK_BTN_COORD

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
        # 大地图右侧"我的队伍"常驻列表 ROI（compact 模式读取队伍用）。
        # 宽 ROI（team_panel_roi）会读入左边大地图的"民心/成都/元宝/兵法/司南"
        # 等无关文本造成噪声；实测队伍名集中在右侧 x≈1100-1240、
        # 表头"我的队伍"约 y181、队伍行 y≈180-460，故收窄到右列。
        self.my_teams_roi: tuple[int, int, int, int] = p.get(
            "my_teams_roi", (1000, 150, 280, 520))
        # 短促 toast 提示区域（中上部，如“血量不足/无法攻打”）
        # 依据截图 MuMu-20260814-160607-496.png：toast 出现在 (435,242,185,52)
        # 收窄到其浮动安全范围，避免全屏 OCR 噪音
        self.toast_roi: tuple[int, int, int, int] = p.get(
            "toast_roi", (380, 200, 520, 130))
        # 等待动画时间（s）
        self.wait_anim: float = p.get("wait_anim", 1.0)
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
        # Phase 4：本 pass 是否只做了增量（近屏）读取；True 时 selection 走 delta fast-path
        self._phase4_delta_pass: bool = False
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
        return report_mod.dump_params(self)

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
        # 会话目标选择器：一次 run 一个实例（keep/switch 找城 + 计划持久化）
        selector = TargetSelector(self)
        selector.start()
        self.report["role_identity"] = selector.identity or ""
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
            r = self._run_one_pass(selector, on_progress, should_stop)
            total_attacks += r.get("total_attacks", 0)
            # 聚合本轮明细到报告（跨轮累积，供保存诊断用）
            self.report["locations"].extend(r.get("locations", []))
            self.report["attacks"].extend(r.get("attacks", []))
            self.report["skipped"].extend(r.get("skipped", []))
            self.report["errors"].extend(r.get("errors", []))
            if r.get("decided"):
                self.report.setdefault("decisions", []).append(r["decided"])
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
        selector: TargetSelector,
        on_progress: Optional[Callable[[str], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> dict:
        """执行一轮刷取（目标选择状态机攻打一次）。返回该轮统计。"""
        attacks = 0
        rpt = {
            "locations": [],
            "attacks": [],
            "skipped": [],
            "errors": [],
            "total_attacks": 0,
            "no_target": False,
            "decided": None,
        }

        # 0. 导航：从大地图进入情报 → 城池战事（幂等）
        if not navigation.navigate_to_city_war(self, on_progress, should_stop):
            rpt["errors"].append("进入城池战事页面失败")
            return rpt

        # 1. 目标已锁定且在 GRINDING/keep 状态 → 用廉价近屏增量读取，
        #    状态机只问「有没有新城」。只有全量决策（重选/提升）才做全量扫描。
        delta = (
            selector.current_target is not None
            and selector.state in ("GRINDING", "CHECK_SWITCH")
        )
        self._phase4_delta_pass = delta
        if delta and on_progress:
            on_progress("目标已锁定，使用增量读取探测新城（不重扫整表）")
        locations = (
            list_reader.read_near_locations(
                self, screens=1, on_progress=on_progress, should_stop=should_stop)
            if delta
            else list_reader.read_all_locations(self, on_progress, should_stop)
        )
        rpt["locations"] = [report_mod.loc_to_report(self, lo) for lo in locations]
        if on_progress:
            on_progress(f"识别到 {len(locations)} 个战斗地点")

        # 2. 状态机决策：keep 当前目标 / 切新城（更近 or 优先级地址）/ 恢复计划
        #    delta 标记须贯穿 decision（供 delta fast-path / 提升判断）。
        loc, decision_msg = selector.decide_target(
            locations, on_progress, should_stop)
        self._phase4_delta_pass = False
        if on_progress and decision_msg:
            on_progress(decision_msg)
        rpt["decided"] = decision_msg

        # 3. 无目标 → 结束
        if loc is None:
            if on_progress:
                on_progress("没有可攻打的城市，直接结束")
            rpt["no_target"] = True
            rpt["total_attacks"] = attacks
            return rpt

        if should_stop and should_stop():
            rpt["total_attacks"] = attacks
            return rpt

        if on_progress:
            ratio = (f"{loc.my_troops} vs 敌{loc.enemy_troops}"
                     if loc.my_troops or loc.enemy_troops else "未知兵力")
            on_progress(f"攻打城市：{loc.name}（我{ratio}）")

        ok = attack.attack_one(self, loc, on_progress, should_stop)
        rpt["attacks"].append(report_mod.loc_to_report(self, loc, attacked=ok))
        if ok:
            attacks += 1
            selector.note_attack(loc, ok)
        else:
            rpt["skipped"].append(report_mod.loc_to_report(self, loc))
            # 本城市攻打失败（非粮尽）→ 本会话内不再重试它，改打别的城市
            if not self._food_exhausted:
                if on_progress:
                    on_progress(f"本轮未能攻打 {loc.name}，后续轮次跳过该城")
                self._blocked_cities.add(loc.name)
        rpt["total_attacks"] = attacks
        return rpt

    # ---------------- 对外便捷方法（委托到模块，保持原契约） ----------------

    def read_my_teams(self, on_progress=None) -> list[dict]:
        """读取大地图右侧常驻队伍列表，返回队伍字典列表。"""
        return team_panel.read_my_teams(self, on_progress)

    def save_report(self, path: str | Path | None = None) -> str:
        """保存诊断报告为 JSON，返回文件路径。"""
        return report_mod.save_report(self, path)