"""评分与排序（纯逻辑，无 ctrl 调用）。原样搬运。"""

from .model import BattleLocation
from .util import is_nanman_city


def score(engine, loc: BattleLocation) -> float:
    """计算地点优先级评分。

    依据：
    - 若在优先城市列表：+100
    - 若为南蛮入侵活动城市：+200（南蛮活动期间优先打南蛮城，战功/收益更高）
    - 敌我兵力比：**敌>我才优先，比值越大越好**
      - 敌/我 > 1：值得打，比值越大分越高（敌多战功多）
      - 敌/我 < 1：我强敌弱，不值得优先打 → 降分
    - 已读耗时越短（距离近）越优先
    - 读不到兵力/耗时则给中性分
    """
    s = 0.0
    if loc.name and any(
        kw in loc.name for kw in engine.priority_cities
    ):
        s += 100.0

    # 南蛮入侵活动城市：给比优先城市更高的分，确保活动期间优先打南蛮城。
    # 优先用 list_reader 解析时从敌方列标记的 loc.is_nanman，否则回退名称判定
    # （兼容「南蛮 某城」这种带前缀的地点名）。
    if getattr(loc, "is_nanman", False) or (loc.name and is_nanman_city(loc.name)):
        s += 200.0

    if loc.enemy_troops > 0 and loc.my_troops > 0:
        ratio = loc.enemy_troops / loc.my_troops
        if ratio > 1.0:
            # 敌强我弱/敌多我少：比值越大越优先
            s += min(ratio * 10, 100.0)
        else:
            # 我强敌弱：反向扣分，越悬殊分越低
            s -= min((1.0 / max(ratio, 0.01)) * 10, 100.0)
    elif loc.enemy_troops > 0:
        s += 30.0  # 有敌情但不知我方，给中性偏上分
    elif loc.my_troops > 0 and loc.enemy_troops == 0:
        s -= 20.0  # 只有我方没敌方，不太值得打
    else:
        s -= 10.0  # 敌我都未知，降低优先级

    if loc.cost_time > 0:
        # 耗时越短分越高
        s += max(0.0, 100.0 - loc.cost_time / 6.0)
    elif loc.cost_time == 0:
        s += 10.0  # 未判断耗时，给基础分

    return s


def rank_locations(engine, locations: list[BattleLocation],
                   on_progress=None) -> list[BattleLocation]:
    """给地点打分并排序，返回建议攻打列表（降序）。

    过滤规则：只攻打「敌方队伍数量 > 我方队伍数量」的地点（敌强我弱/敌多我少），
    排除敌≤我（我方不占优）的地点——这些不在考虑范围内。
    """
    for loc in locations:
        loc.score = score(engine, loc)
    ranked = [
        lo for lo in locations
        if lo.attackable and lo.enemy_troops > lo.my_troops
        and lo.name not in engine._blocked_cities
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