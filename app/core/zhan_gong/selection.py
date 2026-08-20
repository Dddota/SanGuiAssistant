"""目标选择状态机：keep/switch 选城 + 优先级地址覆盖 + 计划持久化。

一次引擎 run() 对应一个会话内的 TargetSelector（会话级，含会话内缓存状态，
不可持久化；永久状态仅经 config 的 per-role 计划/优先级地址持久化）。

状态机（每 pass 一次 decide_target）：
  1. 优先级地址（若配置且存在可攻打匹配城）→ 总是切换过去（优先级最高）
  2. 恢复持久化计划（on resume 首次 decide）
  3. 无当前目标 → 从 ranked 选最优（沿用旧行为）
  4. 有当前目标：
     a. 目标已从列表消失 / 不再可攻打 → 清计划，重新选最优
     b. 目标仍在：
        - 出现「新城」(此前未见过且可攻打) → 探测其耗时，若 < 当前目标耗时则切换
        - 否则保持当前目标
"""
from __future__ import annotations

import datetime
import logging

from .. import config
from . import attack
from . import scoring

logger = logging.getLogger("sangui.zhangong.selection")


class TargetSelector:
    """会话级目标选择状态机。每个引擎 run() 构造一次。"""

    def __init__(self, engine):
        self.engine = engine
        # 当前目标城市（BattleLocation，会话内缓存）
        self.current_target = None
        # 本会话已见过的所有地点名（用于识别"新城"）
        self.seen_cities: set[str] = set()
        # 当前角色身份（命名空间）
        self.identity = config.current_identity() or ""
        # 已加载的计划（会话内重校验后变为 current_target）
        self.plan = config.get_role_plan(self.identity) if self.identity else None
        self.state = "UNPLANNED"
        # 会话内已探测过耗时的地点名（避免重复 O(N) 探测；"lazy probe"）
        self._cost_probed: set[str] = set()
        # 目标选定那次 pass 的全量列表缓存（Delta 读取用；keep 路径复用）
        self.cached_full: list = []

    # ---------------- 生命周期 ----------------

    def start(self) -> None:
        """引擎 run() 开始时调用：载入 per-role 计划，校验角色身份匹配。

        计划目标是否仍存在/可攻打在首次 decide_target 用新鲜列表重校验。
        """
        self.identity = config.current_identity() or ""
        if not self.identity:
            self.plan = None
            self.state = "UNPLANNED"
            return
        plan = config.get_role_plan(self.identity)
        if plan and plan.get("role_identity") == self.identity:
            self.plan = plan
            self.state = "CHECK_SWITCH"
        else:
            self.plan = None
            self.state = "UNPLANNED"

    def clear_session(self) -> None:
        """清空会话内目标与计划（例如粮尽结束时）。"""
        self.current_target = None
        self.plan = None
        self.state = "UNPLANNED"
        self.engine.report.pop("persisted_plan", None)

    # ---------------- 主决策 ----------------

    def decide_target(self, locations, on_progress=None, should_stop=None):
        """根据新鲜的地点列表决定本 pass 攻打哪个城。

        返回 (loc, msg)：loc 为 None 表示无目标可打（结束本轮/会话）。
        msg 为给 on_progress 的决策说明。
        """
        # Phase 4：引擎按 pass 类型传入 全量(repick/UNPLANNED) 或 廉价近屏(delta/GRINDING)。
        # 拿到全量时缓存，供后续 keep 决策；拿近屏时说明是 delta pass。
        is_delta = bool(getattr(self.engine, "_phase4_delta_pass", False))
        if not is_delta:
            self.cached_full = list(locations)

        # ---- 0. 优先级地址总是优先（全量 与 近屏 路径都要先检查） ----
        pa = self._match_priority_address(locations)
        if pa:
            self._set_target(pa)
            self.seen_cities |= {lo.name for lo in locations if lo.name}
            return pa, f"优先级地址命中，切换目标到 {pa.name}"

        # ---- 0.1 南蛮入侵活动：若有可攻打的南蛮城，优先切换过去 ----
        #   （限时活动收益更高，优先于普通城市；优先级地址若也配置了南蛮城，
        #     上面的 pa 分支已生效。此处处理的是未把南蛮城设为优先级地址的普通情况。）
        nm = self._match_nanman_city(locations)
        if nm:
            self._set_target(nm)
            self.seen_cities |= {lo.name for lo in locations if lo.name}
            return nm, f"南蛮入侵进行中，优先攻打南蛮城 {nm.name}"

        # ---- delta keep-path 快路径：只问「有没有新城」 ----
        # 目标已锁定且本轮只读了近屏 → 无新城则直接保持，不做全量读取/全量探测。
        if is_delta and self.current_target is not None:
            if not self._delta_has_new_attackable(locations, on_progress):
                self._ingest_names(locations)
                if on_progress:
                    on_progress(
                        f"增量探测无新城，保持目标 {self.current_target.name}（不重读/不重探）")
                return self.current_target, f"无新城，保持目标 {self.current_target.name}"
            # 出现新城 → 提升为全量决策（用于判断是否更近/重排）
            if on_progress:
                on_progress("增量探测发现新城，提升读取完整列表决定是否切换...")
            return self._promote_delta_to_full(on_progress, should_stop)

        # 本 pass 所有地点名；"新城"判定基于此前 pass 已见过的集合（见下方）
        screen_names = {lo.name for lo in locations if lo.name}
        was_seen = set(self.seen_cities)  # 此前 pass 的已见集合（尚未纳入本 pass）

        # ---- 1. 恢复持久化计划（首次 decide 时，无当前目标） ----
        if self.current_target is None and self.plan and self.state == "CHECK_SWITCH":
            resumed = self._revalidate_plan(locations)
            if resumed:
                self._set_target(resumed)
                self.seen_cities |= screen_names
                if on_progress:
                    on_progress(f"恢复打磨目标 {resumed.name}（持久化计划，{self.plan.get('target_cost', 0)}s）")
                return resumed, f"恢复攻打目标 {resumed.name}"
            # 计划目标失效 → 清计划，重选
            if on_progress:
                on_progress("持久化计划的目标已失效，清空计划重新选择")
            self._clear_plan()

        # ---- 2. ranked 候选池（排除 blocked + 不可打 + 敌≤我） ----
        ranked = scoring.rank_locations(self.engine, locations, on_progress)

        # 当前目标 present 与否
        cur = self.current_target
        cur_present = None
        if cur:
            cur_present = next((l for l in locations if l.name == cur.name), None)

        if cur_present is None:
            # 无目标 或 目标已消失/不可打 → 重选最优
            if not ranked:
                self.current_target = None
                self.seen_cities |= screen_names
                return None, "没有可攻打的城市"
            best = ranked[0]
            was = cur.name if cur else "?"
            # 初始/重选：只对新候选探测耗时（lazy probe），避免重复 O(N) 探测
            unprobed = [l for l in ranked if l.name not in self._cost_probed]
            if len(ranked) > 1 and unprobed and not self.engine.skip_probe:
                ranked = attack.probe_cost_times(
                    self.engine, unprobed, on_progress, should_stop)
                for ploc in ranked:
                    self._cost_probed.add(ploc.name)
                best = ranked[0] if ranked else best
            self._cost_probed.add(best.name)
            self._set_target(best)
            self.seen_cities |= screen_names
            if cur is None:
                return best, f"选定最优城市 {best.name}（我{best.my_troops} vs 敌{best.enemy_troops}）"
            return best, f"目标 {was} 已消失/不可打，重新选择最优城市 {best.name}"

        # ---- 3. 目标仍在 → keep/switch ----
        # "新城" = 可攻打的候选里，此前 pass 未见过（was_seen，而非本 pass），
        #          同时本会话内尚未探测过耗时（lazy probe：避免反复全量探测）。
        new_attackable = [
            l for l in ranked
            if l.name not in was_seen and l.name not in self._cost_probed
        ]
        closer = self._closest_new(new_attackable, cur_present, on_progress, should_stop)
        if closer:
            self._set_target(closer)
            self.seen_cities |= screen_names
            return closer, f"新城更近，切换目标到 {closer.name}"
        self._set_target(cur_present)
        self.seen_cities |= screen_names
        return cur_present, f"无新城，保持目标 {cur_present.name}"

    # ---------------- 决策辅助 ----------------

    def _ingest_names(self, locations) -> None:
        """把给定列表中出现的所有地点名并入已见集合（用于 delta 无新城时）。"""
        for lo in locations:
            if lo and lo.name:
                self.seen_cities.add(lo.name)

    def _delta_has_new_attackable(self, near_locs, on_progress=None) -> bool:
        """delta 快路径：近屏名单里是否出现「此前未见且可攻打」的新城。

        只看「有没有」新城，不做耗时比较（探测放在提升后的全量决策做）。
        """
        new_count = 0
        for lo in near_locs:
            if not lo or not lo.name:
                continue
            if lo.name in self.seen_cities:
                continue
            if lo.attackable and lo.enemy_troops > lo.my_troops \
                    and lo.name not in self.engine._blocked_cities:
                new_count += 1
                if on_progress:
                    on_progress(
                        f"增量探测发现新城：{lo.name}（我{lo.my_troops} vs 敌{lo.enemy_troops}）")
        return new_count > 0

    def _promote_delta_to_full(self, on_progress=None, should_stop=None):
        """delta 近屏发现新城 → 提升到全量列表并走完整状态机决策。

        复用 `decide_target` 的全量分支：把引擎标记为非 delta，读全量列表，
        然后递归调用自身（此时 delta 快路径被禁用，走 keep/switch 完整逻辑）。
        """
        from . import list_reader
        engine = self.engine
        engine._phase4_delta_pass = False
        if on_progress:
            on_progress("读取完整城池战事列表以决策是否切换...")
        full = list_reader.read_all_locations(
            engine, on_progress, should_stop)
        return self.decide_target(full, on_progress, should_stop)

    def _match_priority_address(self, locations):
        """若配置了优先级地址且存在可攻打匹配城，返回它；否则 None。"""
        addr = config.get_role_priority_address(self.identity)
        addr = (addr or "").strip()
        if not addr:
            return None
        for loc in locations:
            if not loc.attackable or not loc.name:
                continue
            if addr in loc.name or loc.name in addr:
                return loc
        return None

    def _match_nanman_city(self, locations):
        """若有可攻打的南蛮入侵城市，返回其中评分最高的一座；否则 None。

        南蛮入侵活动期间，多数情况下「南蛮」出现在敌方国名列（loc.is_nanman
        由列表解析时从敌方列标记）；旧版本地城名也可能是「南蛮 某城」兜底。
        这里统一用 loc.is_nanman（含两种来源），选出可攻打且敌>我的评分最高的
        南蛮城，作为当前 pass 的优先目标（切过去打）。
        若暂无任何可打南蛮城（活动未开始/已结束/全不可打），返回 None 走普通逻辑。
        """
        best, best_score = None, -1.0
        for loc in locations:
            if not loc.attackable or not loc.name:
                continue
            if not loc.is_nanman:
                continue
            if loc.enemy_troops > 0 and loc.enemy_troops <= loc.my_troops:
                continue  # 我强敌弱或敌≤我，不划算也不符合攻打前提
            s = scoring.score(self.engine, loc)
            if s > best_score:
                best, best_score = loc, s
        return best

    def _closest_new(self, new_attackable, current_loc,
                     on_progress=None, should_stop=None):
        """在攻击候选新城中，探测耗时后返回"比当前目标更近"的最近都市；无则 None。

        用户 skip_probe 时不探测，直接以列表内已有 cost_time 参与比较。
        """
        cur_cost = current_loc.cost_time or 0
        if cur_cost <= 0 or not new_attackable:
            return None
        if not self.engine.skip_probe:
            # 探测新城耗时（distance）——lazy：只探测此前未探过的
            probed = attack.probe_cost_times(
                self.engine, list(new_attackable), on_progress, should_stop)
            for ploc in probed:
                if ploc.name:
                    self._cost_probed.add(ploc.name)
        else:
            probed = list(new_attackable)
        best = None
        best_cost = cur_cost
        for loc in probed:
            c = loc.cost_time or 0
            if 0 < c < best_cost:
                best, best_cost = loc, c
        return best

    def _revalidate_plan(self, locations):
        """用新鲜列表重校验持久化计划：目标仍在且可攻打 → 返回其 BattleLocation，否则 None。"""
        if not self.plan:
            return None
        target_name = self.plan.get("target_name")
        if not target_name:
            return None
        loc = next((l for l in locations if l.name == target_name), None)
        if loc and loc.attackable:
            if not loc.cost_time and self.plan.get("target_cost"):
                loc.cost_time = self.plan["target_cost"]
            return loc
        return None

    # ---------------- 计划持久化 ----------------

    def _set_target(self, loc) -> None:
        self.current_target = loc
        self.seen_cities.add(loc.name)
        self.state = "GRINDING"
        self._save_plan()

    def _save_plan(self) -> None:
        """把当前目标切为 per-role 计划（磁盘持久化）。保留既有 attack_count。"""
        if not self.identity or not self.current_target:
            return
        prev = config.get_role_plan(self.identity) or {}
        try:
            prev_count = int(prev.get("attack_count") or 0)
        except (TypeError, ValueError):
            prev_count = 0
        plan = {
            "target_name": self.current_target.name,
            "target_cost": self.current_target.cost_time or 0,
            "attack_count": prev_count,
            "chosen_at_ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "role_identity": self.identity,
        }
        config.save_role_plan(self.identity, plan)

    def _clear_plan(self) -> None:
        self.plan = None
        self.state = "UNPLANNED"
        if self.identity:
            config.save_role_plan(self.identity, {})  # 空计划视为清除

    def note_attack(self, loc, ok: bool) -> None:
        """攻击记一次（更新计划里的 attack_count 并持久化）。"""
        if not ok or not self.identity or not loc:
            return
        plan = config.get_role_plan(self.identity) or {}
        plan["attack_count"] = int(plan.get("attack_count") or 0) + 1
        plan["target_name"] = loc.name
        plan["role_identity"] = self.identity
        config.save_role_plan(self.identity, plan)