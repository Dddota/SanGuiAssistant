"""战斗地点列表读取与解析（OCR 屏幕解析/行列分组/兵力解析）。原样搬运。"""

import logging
import re
import time

from .model import BattleLocation
from .constants import HEADER_KEYWORDS, ENEMY_PREFIXES, LOCATION_NAME_NOISE, LOCATION_MIN_CHINESE
from .util import parse_troop_number, clean_city_name, is_nanman_city

logger = logging.getLogger("sangui.zhangong")


def _is_nanman_faction(enemy_text: str) -> bool:
    """判断敌方国家列是否为南蛮。

    敌方列平时显示 吴/蜀/魏，南蛮入侵活动时显示为"南蛮"。
    """
    if not enemy_text:
        return False
    return "南蛮" in enemy_text or "蛮族" in enemy_text


def read_locations(engine) -> list[BattleLocation]:
    """OCR 战斗地点表格（单屏），返回 BattleLocation 列表。

    表格结构（5列）：战争状态 | 敌方 | 我方队伍数量 | 敌方队伍数量 | 战斗地点
    解析方式：先找表头行确定每列 x 范围，再把数据行条目按 x 归入对应列。
    """
    try:
        results = engine.ctrl.ocr(roi=engine.list_roi)
    except Exception as e:  # noqa: BLE001
        logger.warning("战斗地点列表 OCR 失败: %s", e)
        engine.report["errors"].append(f"列表OCR失败: {e}")
        return []
    return parse_locations_screen(engine, results)


def parse_locations_screen(engine, results: list[dict]) -> list[BattleLocation]:
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
    rows = group_into_rows(items)
    if not rows:
        return []

    # 找表头行，确定列边界
    col_edges = find_column_edges(engine, rows)

    locations = []
    for row in rows:
        if is_header_row(engine, row):
            continue
        loc = parse_table_row(engine, row, col_edges)
        if loc and is_valid_location(engine, loc):
            locations.append(loc)
        else:
            logger.info("过滤掉行: %s",
                        [(it["text"], it["x"], it["y"]) for it in row])
    return locations


def read_all_locations(engine, on_progress=None, should_stop=None,
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
    scroll_to_top(engine)
    if on_progress:
        on_progress("已滚动到列表顶部，开始读取...")

    for scroll_no in range(engine.max_scrolls + 1):
        if should_stop and should_stop():
            break
        try:
            results = engine.ctrl.ocr(roi=engine.list_roi)
        except Exception as e:  # noqa: BLE001
            logger.warning("滚动列表 OCR 失败: %s", e)
            break
        screen_locs = parse_locations_screen(engine, results)
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
            if idle >= engine.scroll_idle_limit:
                break
        else:
            idle = 0
        # 向上滚动一屏（列表可拖动）
        scroll_list_down(engine)
    # 回滚到列表顶部
    scroll_to_top(engine)
    return list(seen.values())


def read_near_locations(engine, screens: int = 1,
                        on_progress=None, should_stop=None) -> list[BattleLocation]:
    """从列表顶部只读前 `screens` 屏的战斗地点，用于 CHECK_SWITCH 的廉价增量探测。

    不做到底部全量扫描（避免 DOMINANT 的 scroll-to-bottom+scroll-to-top 成本）。
    调用方用返回的这批地点判断「是否出现新城」；发现新城需完整决策时再全量读。
    """
    seen: dict[str, BattleLocation] = {}
    scroll_to_top(engine)
    if on_progress:
        on_progress(f"读取列表前 {screens} 屏（增量探测）...")
    for _ in range(max(1, screens)):
        if should_stop and should_stop():
            break
        try:
            results = engine.ctrl.ocr(roi=engine.list_roi)
        except Exception as e:  # noqa: BLE001
            logger.warning("增量列表 OCR 失败: %s", e)
            break
        for loc in parse_locations_screen(engine, results):
            if loc.name and loc.name not in seen:
                seen[loc.name] = loc
        scroll_list_down(engine)
    scroll_to_top(engine)
    return list(seen.values())


def scroll_list_down(engine) -> None:
    """向上滑动列表（内容向下滚动，露出下方更多城市）。

    手机列表：手指从下往上滑（y 大→y 小），列表内容才向下滚动露出后续项。
    用 scroll_step 控制滚动距离（约 2/3 屏高），避免跳太多或太少。
    滚动后等待动画稳定，避免 OCR 读到模糊/错位内容。
    """
    x, y, w, h = engine.list_roi
    xc = x + w // 2
    step = engine.scroll_step
    # 起点在列表偏下方，终点在列表偏上方，距离 = step
    start_y = y + h // 2 + step // 2
    end_y = y + h // 2 - step // 2
    # 限制不超出列表范围
    start_y = min(start_y, y + h - 30)
    end_y = max(end_y, y + 30)
    engine.ctrl.swipe(xc, start_y, xc, end_y, duration_ms=500)
    # 等待滚动动画稳定后再 OCR
    time.sleep(max(engine.wait_anim, 1.2))


def scroll_to_top(engine) -> None:
    """反复下拉（内容回到顶部）直到列表回到顶部。

    手机列表：手指从上往下滑（y 小→y 大），列表内容向上滚动回到顶部。
    用连续多次大跨度下滑确保回到顶部，最后等动画稳定。
    """
    x, y, w, h = engine.list_roi
    xc = x + w // 2
    # 从接近顶部滑到底部附近，每次滑 h-60，确保最大限度滚动
    top_y = y + 40
    bottom_y = y + h - 40
    for _ in range(6):
        engine.ctrl.swipe(xc, top_y, xc, bottom_y, duration_ms=500)
        time.sleep(0.5)
    # 等动画完全稳定
    time.sleep(1.0)


def find_column_edges(engine, rows: list[list[dict]]) -> list[int]:
    """从表头行确定列边界（每列的 x 中心分隔线）。

    返回 n 个分界 x 坐标，把平面切成 n+1 个列区间。
    如果找不到表头，返回空列表，调用方需做兜底。
    """
    header_row = None
    for row in rows:
        if is_header_row(engine, row):
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


def group_into_rows(items: list[dict]) -> list[list[dict]]:
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


def is_header_row(engine, row: list[dict]) -> bool:
    """判断是否为表头行。"""
    header_count = 0
    for it in row:
        for kw in HEADER_KEYWORDS:
            if kw in it["text"]:
                header_count += 1
                break
    return header_count >= 2  # 命中≥2个表头关键词


def parse_table_row(engine, row: list[dict],
                    col_edges: list[int]):
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
        cols = assign_to_columns(row, col_edges)
        if not cols or not cols[-1]:
            return parse_row_fallback(engine, row)

        location_col = cols[-1]
        name_text = "".join(it["text"] for it in location_col)
        name = clean_city_name(name_text)
        if not name:
            return parse_row_fallback(engine, row)

        loc = BattleLocation(name=name)

        # 敌方列（cols[1]）内容为"南蛮"时标记南蛮入侵敌方，
        # 便于选城时优先攻打南蛮城。
        enemy_col_text = ""
        if len(cols) >= 2 and cols[1]:
            enemy_col_text = "".join(it["text"] for it in cols[1])
        loc.is_nanman = _is_nanman_faction(enemy_col_text) or is_nanman_city(name)

        rightmost = max(location_col, key=lambda it: it["x"] + it["w"])
        loc.x = rightmost["x"] + rightmost["w"] // 2
        loc.y = rightmost["y"] + rightmost["h"] // 2

        if len(cols) >= 3 and cols[2]:
            my_text = "".join(it["text"] for it in cols[2])
            loc.my_troops = parse_troop_number(my_text)

        if len(cols) >= 4 and cols[3]:
            enemy_text = "".join(it["text"] for it in cols[3])
            loc.enemy_troops = parse_troop_number(enemy_text)

        if loc.my_troops == 0 or loc.enemy_troops == 0:
            my, enemy = extract_troops_fallback(engine, all_text)
            if loc.my_troops == 0:
                loc.my_troops = my
            if loc.enemy_troops == 0:
                loc.enemy_troops = enemy
    else:
        # 列边界为空：走智能兜底解析
        loc = parse_row_fallback(engine, row)
        if not loc:
            return None

    logger.info("解析 %s: 我=%d 敌=%d", loc.name, loc.my_troops, loc.enemy_troops)
    return loc


def is_valid_location(engine, loc: BattleLocation) -> bool:
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

    if name in LOCATION_NAME_NOISE:
        return False

    if re.match(r"^[\d+\-]+$", name):
        return False

    chinese_chars = re.findall(r"[\u4e00-\u9fa5]", name)
    if len(chinese_chars) < LOCATION_MIN_CHINESE:
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


def parse_row_fallback(engine, row: list[dict]):
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
        enemy_troops = parse_troop_number(enemy_item["text"])

    # 我方兵力：倒数第二个数字条目
    if len(numeric_items) >= 2:
        my_item = numeric_items[-2]
        my_troops = parse_troop_number(my_item["text"])

    # 如果还没找到，用正则关键词兜底
    all_text = " ".join(it["text"] for it in sorted_items)
    if my_troops == 0 or enemy_troops == 0:
        my_fb, enemy_fb = extract_troops_fallback(engine, all_text)
        if my_troops == 0:
            my_troops = my_fb
        if enemy_troops == 0:
            enemy_troops = enemy_fb

    # 地点名：找含国家前缀或不含数字的中文长文本
    name = extract_location_name(engine, sorted_items)
    if not name:
        return None

    loc = BattleLocation(name=name)
    loc.my_troops = my_troops
    loc.enemy_troops = enemy_troops
    loc.is_nanman = _is_nanman_faction(all_text) or is_nanman_city(name)

    # 点击位置：最右侧条目的中心
    rightmost = max(sorted_items, key=lambda it: it["x"] + it["w"])
    loc.x = rightmost["x"] + rightmost["w"] // 2
    loc.y = rightmost["y"] + rightmost["h"] // 2

    return loc


def extract_location_name(engine, sorted_items: list[dict]) -> str:
    """从按 x 排序的 OCR 条目中提取战斗地点名称。

    策略：
    - 优先找含国家前缀（吴国/蜀国/魏国/进攻X国）的条目
    - 否则找最右侧的非数字中文长文本
    - 去掉末尾的 > 箭头等符号
    """
    # 找含国家前缀的条目
    for it in sorted_items:
        t = it["text"]
        for prefix in ENEMY_PREFIXES:
            if prefix in t and len(t) >= 3:
                name = clean_city_name(t)
                if name:
                    return name

    # 找最右侧的纯中文（含国家/城名）文本作为地点名
    # 表格结构从左到右：战争状态 | 敌方 | 我方数 | 敌方数 | 战斗地点
    # 地点名一定在最右侧，所以从右往左找第一个符合条件的
    for it in reversed(sorted_items):
        t = it["text"]
        if re.search(r"[\u4e00-\u9fa5]{2,}", t) and not re.search(r"\d", t):
            cleaned = clean_city_name(t)
            if cleaned:
                return cleaned

    # 最后兜底：取最右侧文本尝试清理
    for it in reversed(sorted_items):
        t = clean_city_name(it["text"])
        if len(t) >= 2:
            return t

    return ""


def assign_to_columns(row: list[dict],
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


def extract_troops_fallback(engine, all_text: str) -> tuple[int, int]:
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
        my = parse_troop_number(m.group(1))
    m2 = re.search(r"敌(?:方|军|队伍|兵)?[^0-9]{0,6}(\d+(?:\+\d+)?)", all_text)
    if m2:
        enemy = parse_troop_number(m2.group(1))

    if my > 0 and enemy > 0:
        return my, enemy

    # 纯数字兜底：找所有数字段（支持 a+b）
    num_tokens = re.findall(r"\d+(?:\+\d+)?", all_text)
    if num_tokens:
        if my == 0 and len(num_tokens) >= 2:
            my = parse_troop_number(num_tokens[0])
        if enemy == 0:
            enemy = parse_troop_number(num_tokens[-1])

    return my, enemy