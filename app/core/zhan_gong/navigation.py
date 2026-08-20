"""地图/面板导航与模板/Ocr 点击辅助。

Phase 4 增强：
  - 引入 `screen_state()` 屏幕状态探测：on-world-map / intel / city-war-list /
    attack-panel，供导航做幂等判断，避免盲目点空白/返回。
  - `navigate_to_city_war` 幂等化：已处城池战事列表直接跳过，只有真正需要时才回大地图。
  - `close_to_world_map`（原 `back_to_world_map` 的 detect-then-close 版本）有界、
    有失败信号，不再假设成功。
  - 保留 `back_to_world_map` 旧签名（现在返回 bool，调用方忽略返回值不破坏契约）。
"""

import logging
import time

from .constants import (
    INTEL_BTN_COORD,
    CITY_WAR_TAB_COORD,
    WORLD_MAP_BLANK,
    BACK_BTN_COORD,
)
from .util import sleep_interruptible

logger = logging.getLogger("sangui.zhangong")

# 城池战事列表专属表头关键词（避免用宽泛的"状态/地点"误判其它页面）
_CITY_WAR_HEADER_KWS = (
    "战争状态", "战斗地点", "我方队伍数量", "敌方队伍数量",
    "我方兵力", "敌方兵力",
)
# 攻菜面板专属关键词（攻城卡片含 耗时/补兵/攻城）
_ATTACK_PANEL_KWS = ("耗时", "补兵", "攻城", "一键补兵")
# 行动菜单专属关键词（点击战斗地点后弹出的菜单，含 攻城/行军/观战/信息/标记）
# 位置对齐 click_city_action 的 menu_roi (740,230,300,250)
_ACTION_MENU_KWS = ("观战", "行军", "攻城", "标记", "信息")


def click_template(engine, template: str, threshold: float = 0.7,
                   max_retries: int = 3, wait_after: float = 1.0,
                   on_progress=None, desc: str = "") -> bool:
    """通过模板匹配找到并点击。返回是否成功。"""
    for _ in range(max_retries):
        try:
            boxes = engine.ctrl.recognize(template, threshold)
            if boxes:
                x, y, w, h, s = boxes[0]
                cx, cy = x + w // 2, y + h // 2
                engine.ctrl.click(cx, cy)
                time.sleep(wait_after)
                if on_progress:
                    on_progress(f"点击{desc}：({cx},{cy}) score={s:.2f}")
                return True
        except Exception as e:  # noqa: BLE001
            logger.debug("模板匹配失败 %s: %s", template, e)
        time.sleep(0.5)
    return False


def template_found(engine, template: str, threshold: float = 0.7) -> bool:
    """只检测模板是否出现在屏幕上（不点击）。返回是否命中。"""
    try:
        boxes = engine.ctrl.recognize(template, threshold)
        return bool(boxes)
    except Exception as e:  # noqa: BLE001
        logger.debug("模板检测失败 %s: %s", template, e)
        return False


def click_text(engine, keyword: str, max_retries: int = 3,
               wait_after: float = 1.0) -> bool:
    """通过 OCR 找到含有关键词的文本并点击其中心。返回是否成功。"""
    for _ in range(max_retries):
        try:
            results = engine.ctrl.ocr()
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
                engine.ctrl.click(cx, cy)
                time.sleep(wait_after)
                return True
        except Exception as e:  # noqa: BLE001
            logger.debug("OCR 点击失败 %s: %s", keyword, e)
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------- 屏幕状态探测

def _is_city_war_list(engine) -> bool:
    """是否处在城池战事列表（表格表头行特征）。"""
    try:
        results = engine.ctrl.ocr(roi=engine.list_roi)
    except Exception as e:  # noqa: BLE001
        logger.debug("city_war 检测 OCR 失败: %s", e)
        return False
    hits = 0
    for r in results or []:
        t = (r.get("text") or "").strip()
        for kw in _CITY_WAR_HEADER_KWS:
            if kw in t:
                hits += 1
                if hits >= 2:
                    return True
                break
    return False


def _is_attack_panel(engine) -> bool:
    """是否开着攻城队伍面板（卡片含 耗时/补兵/攻城 等特征）。"""
    try:
        results = engine.ctrl.ocr(roi=engine.team_panel_roi)
    except Exception as e:  # noqa: BLE001
        logger.debug("attack_panel 检测 OCR 失败: %s", e)
        return False
    for r in results or []:
        t = (r.get("text") or "").strip()
        for kw in _ATTACK_PANEL_KWS:
            if kw in t:
                return True
    return False


def _is_action_menu(engine) -> bool:
    """是否弹出了城池行动菜单（点击战斗地点后，含 攻城/行军/观战 按钮）。"""
    try:
        results = engine.ctrl.ocr(roi=(740, 230, 300, 250))
    except Exception as e:  # noqa: BLE001
        logger.debug("action_menu 检测 OCR 失败: %s", e)
        return False
    for r in results or []:
        t = (r.get("text") or "").strip()
        for kw in _ACTION_MENU_KWS:
            if kw in t:
                return True
    return False


def _is_intel_panel(engine) -> bool:
    """是否开着情报面板（含城池战事页签文本、且非列表/攻菜面板）。"""
    try:
        results = engine.ctrl.ocr()
    except Exception as e:  # noqa: BLE001
        logger.debug("intel_panel 检测 OCR 失败: %s", e)
        return False
    for r in results or []:
        t = (r.get("text") or "").strip()
        if "城池战事" in t:
            return True
    return False


def screen_state(engine) -> str:
    """廉价探测当前屏幕状态。返回：
    - "city_war"    城池战事列表已开
    - "attack_panel" 攻城队伍面板已开
    - "action_menu" 城池行动菜单已弹出（含 攻城/行军/观战 按钮）
    - "world_map"   大地图（右侧常驻队伍列表含"队"）
    - "intel"       情报面板已开但尚未切到城池战事
    - "unknown"     无法确认（尽力探测后仍不确定）
    顺序：先最具体的列表/面板特征，再大地图/情报，最后 unknown。
    """
    if _is_city_war_list(engine):
        return "city_war"
    if _is_attack_panel(engine):
        return "attack_panel"
    if _is_action_menu(engine):
        return "action_menu"
    if is_on_world_map(engine):
        return "world_map"
    if _is_intel_panel(engine):
        return "intel"
    return "unknown"


# ---------------------------------------------------------------- 大地图判定

def is_on_world_map(engine) -> bool:
    """检测是否在大地图：右侧队伍区域含'队'字样（且非攻城卡片特征区）。"""
    try:
        # 右侧队伍列表区域：x≈1080-1260, y≈200-500
        results = engine.ctrl.ocr((1080, 200, 180, 300))
        for r in results:
            text = (r.get("text") or "").strip()
            if "队" in text and len(text) >= 2:
                return True
    except Exception as e:  # noqa: BLE001
        logger.debug("is_on_world_map OCR 失败: %s", e)
    return False


# ---------------------------------------------------------------- 回到大地图

def close_to_world_map(engine, on_progress=None, should_stop=None) -> bool:
    """关闭任意面板/浮层回到大地图。detect-then-close，有界，返回是否确认成功。

    策略：先探测是否已在大地图；若不在，循环「点空白关浮层 → 探测」，
    仍不回则点左上角返回键，最多若干次；最后点空白兜底。
    不再盲目点固定次数后假设成功——最终以 `is_on_world_map` 确认为准，
    无法确认时返回 False（调用方应据此硬失败而非继续）。
    """
    # 已在大地图 → 直接成功
    if is_on_world_map(engine):
        if on_progress:
            on_progress("已处在大地图像，无需跳转")
        return True

    if on_progress:
        on_progress("导航到大地图（点空白/返回，探测确认）...")

    # 第一步：点空白关浮层（最多若干次）
    for _ in range(4):
        if should_stop and should_stop():
            return False
        if is_on_world_map(engine):
            if on_progress:
                on_progress("已回到大地图")
            return True
        engine.ctrl.click(WORLD_MAP_BLANK[0], WORLD_MAP_BLANK[1])
        if sleep_interruptible(engine.wait_anim, should_stop):
            return False

    # 第二步：点左上角返回（最多 5 次）
    for _ in range(5):
        if should_stop and should_stop():
            return False
        if is_on_world_map(engine):
            if on_progress:
                on_progress("已回到大地图")
            return True
        engine.ctrl.click(BACK_BTN_COORD[0], BACK_BTN_COORD[1])
        if sleep_interruptible(engine.wait_anim + 0.3, should_stop):
            return False

    # 第三步：点空白兜底
    for _ in range(3):
        if should_stop and should_stop():
            return False
        if is_on_world_map(engine):
            if on_progress:
                on_progress("已回到大地图")
            return True
        engine.ctrl.click(WORLD_MAP_BLANK[0], WORLD_MAP_BLANK[1])
        if sleep_interruptible(engine.wait_anim, should_stop):
            return False

    if on_progress:
        on_progress("警告：未能确认回到大地图（屏幕状态未知）")
    return is_on_world_map(engine)


def back_to_world_map(engine, on_progress=None, should_stop=None) -> bool:
    """旧签名兼容：detect-then-close 回到大地图，返回是否确认成功。"""
    return close_to_world_map(engine, on_progress, should_stop)


# ---------------------------------------------------------------- 进入城池战事

def navigate_to_city_war(engine, on_progress, should_stop=None) -> bool:
    """幂等地进入情报→城池战事列表。返回是否确认成功。

    幂等规则：
      - 已处城池战事列表 → 直接成功（最贵场景：跳过 intel/切页/盲回大地图）。
      - 开在大地图 → 直接点情报 + 切城池战事页签（不盲回）。
      - 开了攻菜面板/情报浮层 → 先 detect-then-close 回大地图，再进情报。
    只有真正需要时才 `close_to_world_map`，且以 `screen_state` 确认，而非假设成功。
    """
    if screen_state(engine) == "city_war":
        if on_progress:
            on_progress("已处在城池战事页面，跳过导航")
        return True
    if should_stop and should_stop():
        return False

    if on_progress:
        on_progress("进入情报→城池战事...")
    for attempt in range(2):
        if should_stop and should_stop():
            return False
        state = screen_state(engine)
        # 若开在攻菜面板/情报浮层：先关面板确认大地图（带硬失败信号）
        if state in ("attack_panel", "intel", "action_menu"):
            if on_progress:
                on_progress(f"检测到 {state}，先回大地图再进入情报...")
            if not close_to_world_map(engine, on_progress, should_stop):
                if attempt == 0:
                    continue
                if should_stop and should_stop():
                    return False
                if on_progress:
                    on_progress("关闭面板确认大地图失败，放弃导航")
                return False

        # 点情报按钮（模板优先，固定坐标兜底）
        ok = click_template(
            engine, "zhan_gong_intel_btn.png",
            threshold=0.6,
            max_retries=3,
            wait_after=1.5,
            on_progress=on_progress,
            desc="情报按钮",
        )
        if not ok:
            ix, iy = INTEL_BTN_COORD
            if on_progress:
                on_progress(
                    f"模板匹配失败，用固定坐标点情报按钮 ({ix},{iy})")
            engine.ctrl.click(ix, iy)
            if sleep_interruptible(1.5, should_stop):
                return False
        if on_progress:
            on_progress("已点击情报按钮，等待面板展开...")

        # 切城池战事页签（OCR 优先，模板兜底）
        ok = click_text(engine, "城池战事", max_retries=3, wait_after=1.5)
        if not ok:
            if on_progress:
                on_progress("OCR 未找到，尝试模板匹配城池战事页签...")
            ok = click_template(
                engine, "zhan_gong_city_war_tab.png",
                threshold=0.6,
                max_retries=3,
                wait_after=1.5,
                on_progress=on_progress,
                desc="城池战事页签",
            )

        # 以屏幕状态确认成功，而非假设
        if screen_state(engine) == "city_war":
            if on_progress:
                on_progress("已确认切换到城池战事页面")
            return True
        if ok:
            if on_progress:
                on_progress("已切换到城池战事页面")
            return True
        if should_stop and should_stop():
            return False

        if on_progress:
            on_progress(
                f"第 {attempt + 1} 次未确认城池战事页，关面板重试...")
        close_to_world_map(engine, None, should_stop)
        if sleep_interruptible(1.0, should_stop):
            return False

    if on_progress:
        on_progress("错误：无法确认进入城池战事页面")
    return False