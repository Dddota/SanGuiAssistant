"""攻打流程：定位城市、攻城、补兵、出征验证、等待战斗返回、toast/弹窗处理。原样搬运。"""

import logging
import time

from .model import BattleLocation
from .constants import (
    UNAVAILABLE_KEYWORDS,
    PANEL_RIGHT_X,
    SUPPLY_ALL_BTN_COORD,
)
from .util import sleep_interruptible
from .navigation import (
    template_found,
    click_template,
    click_text,
    back_to_world_map,
    navigate_to_city_war,
    screen_state,
)
from .list_reader import read_locations, scroll_to_top, scroll_list_down
from .team_panel import (
    parse_team_panel,
    find_target_team,
    find_team_by_name,
    parse_injury_wait,
)

logger = logging.getLogger("sangui.zhangong")


# ---------------------------------------------------------------- 定位

def click_city_by_name(engine, name: str,
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
    if not navigate_to_city_war(engine, on_progress):
        if on_progress:
            on_progress(f"[定位] 无法回到城池战事页面，放弃『{name}』")
        return False

    # 先滚到列表顶部，确保从头开始找
    scroll_to_top(engine)

    # 2. 从顶部开始查找：先读当前屏，找不到则向下滚动继续找
    prev_screen_names: set[str] = set()
    for scroll_idx in range(engine.max_scrolls + 1):
        if should_stop and should_stop():
            return False
        locs = read_locations(engine)
        if not locs:
            if on_progress:
                on_progress(f"[定位] 列表OCR为空，放弃『{name}』")
            return False

        # Phase 4：优先精确匹配，避免共享字符误点他城；无精确命中共用时才回退模糊。
        target = None
        exact = [lo for lo in locs if lo.name == name]
        if exact:
            target = exact[0]
        else:
            # 无精确匹配：仅当模糊候选唯一时才用，降低共享字符误点风险
            fuzzy = [lo for lo in locs
                     if (name in lo.name or lo.name in name) and lo.name != name]
            if len(fuzzy) == 1:
                target = fuzzy[0]
        if target:
            if on_progress:
                on_progress(
                    f"[定位] 在列表({target.x},{target.y})找到"
                    f"『{target.name}』（滚动{scroll_idx}），点击")
            engine.ctrl.click(target.x, target.y)
            if sleep_interruptible(1.5, should_stop):
                return False
            # 廉价校验：点完应弹出该城的行动菜单/队伍面板，而不是误点到他城
            st = screen_state(engine)
            if st not in ("attack_panel", "city_war", "action_menu"):
                if on_progress:
                    on_progress(
                        f"[定位] 点完『{target.name}』屏幕状态异常({st})，"
                        f"视为未命中，继续排查")
                continue
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
        scroll_list_down(engine)
        if sleep_interruptible(0.8, should_stop):
            return False

    if on_progress:
        on_progress(f"[定位] 滚动到底仍未找到『{name}』，放弃")
    return False


# ---------------------------------------------------------------- 行动菜单 / 攻打按钮

def click_city_action(engine, on_progress=None, should_stop=None) -> bool:
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
        if should_stop and should_stop():
            return False
        try:
            results = engine.ctrl.ocr(roi=menu_roi)
        except Exception as e:  # noqa: BLE001
            logger.debug("行动菜单 OCR 失败: %s", e)
            break
        if on_progress:
            texts = [r.get("text", "") for r in results]
            on_progress(f"[行动菜单] 菜单OCR读到: {texts}")
        for r in results:
            text = (r.get("text") or "").strip()
            # 攻城（敌方可攻打）与行军（己方城池出兵）都会触发战斗流程，
            # 命中哪个点哪个，让己方可出兵的城也能被攻打。
            # 出征按钮文案不一：敌方「攻城」、出兵「行军」、可出征队伍「前往」。
            for kw in ("攻城", "行军", "攻打", "前往"):
                if kw in text:
                    box = r.get("box", (0, 0, 0, 0))
                    cx = box[0] + box[2] // 2
                    cy = box[1] + box[3] // 2
                    engine.ctrl.click(cx, cy)
                    if on_progress:
                        on_progress(f"[行动菜单] 点击了『{kw}』({cx},{cy})")
                    return True
        if on_progress:
            on_progress(f"[行动菜单] 未找到攻城/行军，重试 {attempt + 1}/3")
        if sleep_interruptible(1.0, should_stop):
            return False
    return False


def click_attack_btn_on_team(engine, team: dict,
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
    logger.debug("[攻打] 队伍 %s attack_btn=%s row_y=%s btn_y=%s",
                 team.get("name", "?"), team.get("attack_btn"), ry, btn_y)
    if on_progress:
        on_progress(f"[攻打] 菜单已弹出，识别攻打/行军按钮（行y={btn_y}）...")

    # OCR 区域：覆盖卡片右侧按钮区（补兵+攻打），中心放在按钮行（btn_y）。
    # 实测按钮文案（如"前往"）实际比 attack_btn 固定坐标偏下约 50-100px，
    # 旧 roi (btn_y-40, 100h) 纵向只到 btn_y+60，读不到按钮文字直接走固定坐标兜底、
    # 点击偏左上。纵向放大到 btn_y-60 ~ btn_y+100，让"前往/行军/攻打"文字能命中。
    roi = (PANEL_RIGHT_X - 300, btn_y - 60, 320, 160)
    if on_progress:
        on_progress(f"[攻打] OCR区域={roi}")
    try:
        results = engine.ctrl.ocr(roi=roi)
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
                    logger.debug("[攻打] OCR 命中『%s』 box=%s → 点击(%d,%d)",
                                 kw, list(box), cx, cy)
                    engine.ctrl.click(cx, cy)
                    if on_progress:
                        on_progress(f"[攻打] 通过OCR点击了『{kw}』({cx},{cy})")
                    return True
    except Exception as e:  # noqa: BLE001
        logger.debug("攻打按钮 OCR 失败: %s", e)
        if on_progress:
            on_progress(f"[攻打] OCR异常: {e}")

    # 2) 模板匹配攻打按钮图标（zhan_gong_confirm_btn.png 实为攻打按钮）
    if click_template(
        engine, "zhan_gong_confirm_btn.png",
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
        logger.debug("[攻打] OCR/模板未中，固定坐标点攻打 (%d,%d)", x, y)
        engine.ctrl.click(x, y)
        if on_progress:
            on_progress(f"[攻打] OCR未找到文字，固定坐标点攻打 ({x},{y})")
        return True
    # 3) 最后兜底：在行高度上点右侧区域
    fx, fy = PANEL_RIGHT_X - 45, ry
    engine.ctrl.click(fx, fy)
    if on_progress:
        on_progress(f"[攻打] 兜底点右侧 ({fx},{fy})")
    return True


def click_supply_btn(engine, team: dict, on_progress=None) -> bool:
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

    # OCR 区域：覆盖该行按钮区（图标+下方文字），中心放在按钮行上。
    # 纵向与攻打按钮一致放大，避免按钮文字偏下时漏读。
    if btn_y > 0:
        roi = (PANEL_RIGHT_X - 300, btn_y - 60, 320, 160)
        try:
            results = engine.ctrl.ocr(roi=roi)
            for r in results:
                text = (r.get("text") or "").strip()
                if "补兵" in text:
                    box = r.get("box", (0, 0, 0, 0))
                    cx = box[0] + box[2] // 2
                    cy = box[1] + box[3] // 2
                    engine.ctrl.click(cx, cy)
                    if on_progress:
                        on_progress(f"[补兵] OCR点击『补兵』({cx},{cy})")
                    return True
        except Exception as e:  # noqa: BLE001
            logger.debug("补兵按钮 OCR 失败: %s", e)

    if team.get("supply_btn"):
        x, y = team["supply_btn"]
        engine.ctrl.click(x, y)
        if on_progress:
            on_progress(f"[补兵] 固定坐标点补兵 ({x},{y})")
        return True
    # 兜底：攻打按钮左侧
    if team.get("attack_btn"):
        ax, ay = team["attack_btn"]
        engine.ctrl.click(ax - 80, ay)
        return True
    return False


def click_supply_all_btn(engine, on_progress=None) -> bool:
    """点击队伍面板底部的『一键补兵』大按钮（给全部队伍补兵）。

    OCR 在按钮区域找『一键补兵』文字优先；找不到用固定坐标兜底。
    """
    # OCR 区域：面板底部『一键补兵』『一键前往』两枚大按钮所在行
    try:
        roi = (600, 600, 680, 100)
        results = engine.ctrl.ocr(roi=roi)
        for r in results:
            text = (r.get("text") or "").strip()
            if "一键补兵" in text:
                box = r.get("box", (0, 0, 0, 0))
                cx = box[0] + box[2] // 2
                cy = box[1] + box[3] // 2
                engine.ctrl.click(cx, cy)
                if on_progress:
                    on_progress(f"[补兵] OCR点击『一键补兵』({cx},{cy})")
                return True
    except Exception as e:  # noqa: BLE001
        logger.debug("一键补兵按钮 OCR 失败: %s", e)

    # 固定坐标兜底（vision 校准 MuMu-20260814-025514-633.png：
    # 『一键补兵』x≈615-880、y≈620-670 → 中心 (747,645)）
    x, y = SUPPLY_ALL_BTN_COORD
    engine.ctrl.click(x, y)
    if on_progress:
        on_progress(f"[补兵] 固定坐标点『一键补兵』({x},{y})")
    return True


def click_dispatch_all_btn(engine, on_progress=None) -> bool:
    """点击队伍面板底部的『一键派兵』大按钮（一次性派出全部可战队伍）。

    该按钮与『一键补兵』在同一行（位于其右侧）。按文案可能是
    『一键前往』/『一键派兵』/『一键出征』。优先 OCR 识别文字点击；
    找不到返回 False（由调用方回退到逐个攻打），不盲目用固定坐标，
    因为该按钮坐标未校准、位置随文案宽度变化。
    """
    roi = (600, 600, 680, 100)
    try:
        results = engine.ctrl.ocr(roi=roi)
    except Exception as e:  # noqa: BLE001
        logger.debug("一键派兵按钮 OCR 失败: %s", e)
        return False
    logger.debug("[出征] 一键派兵 OCR 读到: %s",
                 [r.get("text", "") for r in results])
    for r in results:
        text = (r.get("text") or "").strip()
        for kw in ("一键前往", "一键派兵", "一键出征"):
            if kw in text:
                box = r.get("box", (0, 0, 0, 0))
                cx = box[0] + box[2] // 2
                cy = box[1] + box[3] // 2
                logger.debug("[出征] 一键派兵 OCR 命中『%s』→ 点击(%d,%d)",
                             kw, cx, cy)
                engine.ctrl.click(cx, cy)
                if on_progress:
                    on_progress(f"[出征] OCR点击『{kw}』({cx},{cy})")
                return True
    if on_progress:
        results2 = engine.ctrl.ocr(roi=roi)
        on_progress(f"[出征] 未识别到一键派兵按钮，OCR读到: "
                    f"{[r.get('text','') for r in results2]}")
    return False


# ---------------------------------------------------------------- 检测 / 弹窗

def has_result_popup(engine) -> bool:
    """判断是否出现战斗结果弹窗（战败/重伤救治提示）。

    模板匹配优先（`zhan_gong_defeat.png`），OCR 关键词兜底。
    注意：本游戏没有胜利弹窗，只有战败弹窗（提示队伍重伤、需粮草救治）。
    """
    # 模板匹配优先
    if template_found(engine, "zhan_gong_defeat.png", threshold=0.6):
        return True
    # OCR 兜底
    try:
        results = engine.ctrl.ocr()
        for r in results:
            text = (r.get("text") or "").strip()
            for kw in ("胜利", "战败", "战败回城", "撤离", "战斗结束"):
                if kw in text:
                    return True
    except Exception as e:  # noqa: BLE001
        logger.debug("结果弹窗判定失败: %s", e)
    return False


def dismiss_result(engine) -> None:
    """关闭战败弹窗（返还粮草提示）。

    逻辑：先点左下角勾选框『今日不再提示』，再点右下角『确认』。
    用模板匹配定位弹窗位置，按模板图内坐标换算勾选框/确认按钮位置；
    模板匹配不到时，OCR 找『确认』文字兜底。
    """
    # 模板图内坐标（zhan_gong_defeat.png 779x289）
    #   勾选框中心约 (57, 244)，确认按钮中心约 (642, 240)
    tpl_w, tpl_h = 779, 289
    try:
        boxes = engine.ctrl.recognize("zhan_gong_defeat.png", 0.6)
        if boxes:
            x, y, w, h, _ = boxes[0]
            sx, sy = w / tpl_w, h / tpl_h
            # 先点左下角勾选框
            cbx, cby = x + 57 * sx, y + 244 * sy
            engine.ctrl.click(round(cbx), round(cby))
            time.sleep(engine.wait_anim)
            # 再点右下角确认
            okx, oky = x + 642 * sx, y + 240 * sy
            engine.ctrl.click(round(okx), round(oky))
            time.sleep(engine.wait_anim)
            return
    except Exception as e:  # noqa: BLE001
        logger.debug("弹窗模板定位失败: %s", e)
    # OCR 兜底：点『确认』
    try:
        click_text(engine, "确认", max_retries=2, wait_after=engine.wait_anim)
    except Exception as e:  # noqa: BLE001
        logger.debug("关闭结果 OCR 失败: %s", e)


def has_no_food(engine) -> bool:
    """补兵后检查是否出现『粮食不足/无粮食』提示。

    模板匹配优先（`zhan_gong_no_food.png`），OCR 关键词兜底。
    """
    # 模板匹配优先
    if template_found(engine, "zhan_gong_no_food.png", threshold=0.6):
        return True
    # OCR 兜底：限定在 toast_roi 区域，避免全屏噪音
    return has_toast(engine,
                     ["粮食不足", "粮草不足", "无粮食", "粮食不够",
                      "粮草不够", "没有粮食", "资源不足"])


def has_toast(engine, keywords: list[str],
              template: str = "") -> bool:
    """在 toast 提示区域检测短促提示（如血量不足/无法攻打）。

    模板匹配优先（若给 template）。OCR 兜底时先读主 toast_roi；
    主区为空（可跳过）或没命中时，回退到次选的窄区域（面板/中上部），
    避免全屏 OCR 引入 UI 文本噪音。
    """
    if template and template_found(engine, template, threshold=0.6):
        return True
    if not keywords:
        return False
    # toast_roi 可为空元组/全零 → 视为跳过 OCR 检测
    try:
        roi = engine.toast_roi or (0, 0, 0, 0)
        if roi[2] <= 0 or roi[3] <= 0:
            return False
        results = engine.ctrl.ocr(roi=roi)
        for r in results:
            text = (r.get("text") or "").strip()
            if any(kw in text for kw in keywords):
                return True
        # 主区没命中：回退到更宽的候选区（2 个标准次选区域），
        # 某些机型 toast 位置有偏移时仍有兜底。
        for fallback in ((120, 180, 440, 160), (440, 180, 400, 120)):
            try:
                results = engine.ctrl.ocr(roi=fallback)
            except Exception:  # noqa: BLE001
                continue
            for r in results:
                text = (r.get("text") or "").strip()
                if any(kw in text for kw in keywords):
                    return True
    except Exception as e:  # noqa: BLE001
        logger.debug("toast 检查 OCR 失败: %s", e)
    return False


def confirm_attack(engine, on_progress=None) -> bool:
    """确认出征（如果有确认弹窗的话）。返回是否点到了确认。"""
    # 模板匹配
    if click_template(
        engine, "zhan_gong_confirm_btn.png",
        threshold=0.6,
        max_retries=2,
        wait_after=engine.wait_anim,
        on_progress=on_progress,
        desc="确认出征按钮",
    ):
        return True

    # OCR 兜底
    for kw in ("立即出征", "出征", "确认出征", "确认", "派兵", "确定"):
        if click_text(engine, kw, max_retries=1, wait_after=engine.wait_anim):
            if on_progress:
                on_progress(f"通过 OCR 点击了『{kw}』")
            return True

    # 检查是否有不可攻打提示（模板优先，OCR 兜底）
    if template_found(engine, "zhan_gong_unavailable.png", threshold=0.6):
        if on_progress:
            on_progress("检测到不可攻打提示（模板）")
        return False
    try:
        results = engine.ctrl.ocr()
        for r in results:
            text = (r.get("text") or "").strip()
            if any(kw in text for kw in UNAVAILABLE_KEYWORDS):
                if on_progress:
                    on_progress(f"检测到不可攻打提示：{text[:20]}")
                return False
    except Exception as e:  # noqa: BLE001
        logger.debug("不可攻打检查 OCR 失败: %s", e)
    # 没有确认弹窗也可能是正常的（直接出兵了）
    return False


def cancel_attack(engine) -> None:
    """取消攻打（关闭弹窗/面板）。"""
    close_team_panel(engine)


# ---------------------------------------------------------------- 面板开关 / 验证

def close_team_panel(engine) -> None:
    """关闭右侧队伍面板（点一下地图空白区域或X）。"""
    try:
        # 点面板外地图区域
        engine.ctrl.click(400, 400)
        time.sleep(engine.wait_anim)
    except Exception as e:  # noqa: BLE001
        logger.debug("关闭面板失败: %s", e)


def verify_team_marching(engine, team_name: str) -> bool:
    """在大地图上通过 compact 队伍列表验证队伍是否出征中。"""
    try:
        teams = parse_team_panel(engine, compact=True)
    except Exception:  # noqa: BLE001
        return False
    t = find_team_by_name(engine, teams, team_name)
    if not t:
        return False
    status = t.get("status", "") or t.get("name", "")
    return any(
        kw in status for kw in
        ("出征中", "行军中", "前往", "抵达", "●", "剩余", "战斗中")
    )


def open_attack_panel_for_city(engine, loc: "BattleLocation",
                               on_progress=None,
                               should_stop=None) -> bool:
    """导航到城池战事，定位城市，点攻城打开攻打面板（幂等）。

    Phase 4：若当前已处于攻城面板/城池战事页，跳过重复导航直接校验定位。
    返回是否成功打开面板（面板已打开即可，不校验内容）。
    """
    st = screen_state(engine)
    # 已在攻城面板：判定为目标城市面板已可复用（多轮攻打时逐轮复用）
    if st == "attack_panel":
        if on_progress:
            on_progress(f"[面板] 已处于攻城面板，复用（跳过重复导航）→ {loc.name}")
        return True
    # 已在城池战事页：直接定位城市，无需重进情报
    if st == "city_war":
        if on_progress:
            on_progress("已处在城池战事页面，直接定位城市（跳过情报/切页）")
    else:
        # 从大地图进入情报→城池战事
        if not navigate_to_city_war(engine, on_progress):
            return False
    # 定位城市
    if not click_city_by_name(engine, loc.name, on_progress):
        return False
    if sleep_interruptible(1.0, should_stop):
        return False
    # 点攻城打开队伍面板
    if not click_city_action(engine, on_progress, should_stop):
        return False
    if sleep_interruptible(1.5, should_stop):
        return False
    return True


# ---------------------------------------------------------------- 主攻打流程

def probe_cost_times(engine, locs: list[BattleLocation],
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
        if not click_city_by_name(engine, loc.name, on_progress, should_stop):
            if on_progress:
                on_progress(f"{loc.name} 定位/点击失败，跳过")
            probed.append(loc)
            continue
        # 识别行动菜单攻打/行军按钮并点击（为读取队伍面板耗时做准备）
        if not click_city_action(engine, on_progress, should_stop):
            if on_progress:
                on_progress(f"{loc.name} 未找到行动菜单攻打/行军按钮")
        if sleep_interruptible(1.0, should_stop):
            break

        teams = parse_team_panel(engine, on_progress)
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
        if loc.cost_time > 0 and loc.cost_time > engine.max_cost_time:
            loc.attackable = False
            loc.skip_reason = (
                f"距离太远（耗时{loc.cost_time}s > {engine.max_cost_time}s）")
            if on_progress:
                on_progress(f"  放弃：{loc.name}（{loc.skip_reason}）")

        probed.append(loc)

        # 关闭面板，回到列表，探测下一个
        close_team_panel(engine)
        if sleep_interruptible(engine.wait_anim, should_stop):
            break
        # 重新导航回城池战事列表（确保每个探测都在列表页触发）
        navigate_to_city_war(engine, on_progress)
        locs_after = read_locations(engine)
        if len(locs_after) != len(locs):
            # 列表行数变化，重新映射坐标到当前列表
            by_name = {lo.name: lo for lo in locs_after}
            for ploc in probed:
                cur = by_name.get(ploc.name)
                if cur:
                    ploc.x, ploc.y = cur.x, cur.y

    return probed


def attack_one(engine, loc: BattleLocation,
               on_progress=None, should_stop=None) -> bool:
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
        if not click_city_by_name(engine, loc.name, on_progress, should_stop):
            if on_progress:
                on_progress(f"放弃：{loc.name}（定位/点击失败）")
            return False

        # 1.5 识别行动菜单上的攻打/行军按钮并点击 → 右侧弹出队伍选择面板
        if not click_city_action(engine, on_progress, should_stop):
            if on_progress:
                on_progress("未找到行动菜单的攻打/行军按钮，尝试直接读队伍面板")
        if sleep_interruptible(1.0, should_stop):
            return False

        # 2-3. 解析右侧队伍面板并找到目标队伍（首次，用于校验）
        teams = parse_team_panel(engine, on_progress)
        if not teams:
            loc.attackable = False
            loc.skip_reason = "未读取到队伍列表"
            if on_progress:
                on_progress(f"放弃：{loc.name}（{loc.skip_reason}）")
            close_team_panel(engine)
            return False
        target = find_target_team(engine, teams, on_progress)
        if not target:
            loc.attackable = False
            loc.skip_reason = (
                f"未找到目标队伍（名称={engine.team_name!r} 序号={engine.team_index}）"
            )
            if on_progress:
                on_progress(f"放弃：{loc.name}（{loc.skip_reason}）")
            close_team_panel(engine)
            return False

        # 4. 首次耗时检查（后续循环不再重复检查距离）
        loc.cost_time = target["cost_time"]
        if on_progress:
            if loc.cost_time > 0:
                on_progress(
                    f"{target['name']} 预计耗时：{loc.cost_time}秒"
                    f"（上限{engine.max_cost_time}秒）"
                )
            else:
                on_progress(f"{target['name']} 未读取到耗时信息，跳过距离检查")
        if loc.cost_time > 0 and loc.cost_time > engine.max_cost_time:
            loc.attackable = False
            loc.skip_reason = f"距离太远（耗时{loc.cost_time}s > {engine.max_cost_time}s）"
            if on_progress:
                on_progress(f"放弃：{loc.name}（{loc.skip_reason}）")
            close_team_panel(engine)
            return False

        # 5. 确定本轮要出战的队伍列表：
        #    若用户勾选了 team_names，则逐个队伍攻打；否则用默认目标队伍
        if engine.team_names:
            target_teams = []
            for tname in engine.team_names:
                found = find_team_by_name(engine, teams, tname)
                if found:
                    target_teams.append(found)
                else:
                    if on_progress:
                        on_progress(f"勾选队伍『{tname}』未在面板中找到，跳过")
            if not target_teams:
                on_progress(f"勾选的队伍都不可用，放弃：{loc.name}")
                close_team_panel(engine)
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
        clicked = click_supply_all_btn(engine, on_progress)
        if clicked:
            if sleep_interruptible(1.5, should_stop):
                return False
            if has_no_food(engine):
                if on_progress:
                    on_progress("补兵失败（无粮食），本轮批量派出放弃")
                engine._food_exhausted = True
                back_to_world_map(engine, on_progress)
                return False

        # 6.2 『一键派兵』会把点城后弹出的队伍面板上所有队伍一次性派出。
        #    判据 = 用户是否在『读取队伍』里勾选了队伍：
        #    - 没读取过 / 没勾选（engine.team_names 为空）→ 用户没指定派谁，
        #      最省事就是点开面板后直接『一键派兵』全派出，再读状态确认。
        #    - 读取并勾选了队伍 → 只派勾选的，逐个点攻打，避免把没勾的也派出去。
        dispatched: list[dict] = []
        used_dispatch_all = False
        dispatch_all_safe = not getattr(engine, "team_names", None)
        # 显式打出一键派兵的决策原因，便于排查看不到触发的问题
        if on_progress:
            on_progress(
                f"【批量第一轮】勾选队伍={'有' if engine.team_names else '无'} → "
                + ("走『一键派兵』(未勾选，直接全派最省事)"
                   if dispatch_all_safe
                   else "已勾选队伍，逐个点攻打勾选的队列")
            )
        if dispatch_all_safe:
            if on_progress:
                on_progress("【批量第一轮】尝试『一键派兵』（未勾选，直接全派）")
            if click_dispatch_all_btn(engine, on_progress):
                used_dispatch_all = True
                dispatched = list(target_teams)
                if sleep_interruptible(3.0, should_stop):
                    return False
                # 一键派兵后检测不可攻打 toast（如有粮不足/无兵等）
                if has_toast(
                    engine, UNAVAILABLE_KEYWORDS,
                    template="zhan_gong_unavailable.png",
                ):
                    if on_progress:
                        on_progress(
                            "『一键派兵』后检测到无法出兵提示，"
                            "部分队伍可能未派出")

        if not used_dispatch_all:
            if on_progress:
                on_progress(
                    f"【批量第一轮】逐个点攻打 {len(target_teams)} 队（"
                    f"勾选数≠面板队伍数，或未识别到『一键派兵』按钮）")
            for t_idx, tgt in enumerate(target_teams, 1):
                if should_stop and should_stop():
                    break
                # 重伤/恢复中队伍：点了攻打也派不出，跳过不点、不计数
                if not tgt.get("attackable", True):
                    if on_progress:
                        on_progress(
                            f"【批量第一轮】队伍重伤/恢复中，跳过不派："
                            f"{tgt.get('name', '?')}")
                    continue
                if on_progress:
                    on_progress(
                        f"【批量第一轮】派出 {t_idx}/{len(target_teams)}："
                        f"{tgt['name']}")
                click_attack_btn_on_team(engine, tgt, on_progress)
                if sleep_interruptible(3.0, should_stop):
                    break
                # 点完攻打检测不可攻打 toast，有则跳过该队
                if has_toast(
                    engine, UNAVAILABLE_KEYWORDS,
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
            back_to_world_map(engine, on_progress)
            return False

        # 6.3 全部点完：关面板回大地图，通过 compact 列表验证出征
        back_to_world_map(engine, on_progress)
        if sleep_interruptible(3.0, should_stop):
            return False
        actually_marching: list[dict] = []
        for tgt in dispatched:
            if should_stop and should_stop():
                break
            team_name = tgt.get("name", "?")
            if verify_team_marching(engine, team_name):
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
        stopped = wait_battle_return_multi(
            engine, loc, actually_marching, on_progress, should_stop)
        if stopped:
            return attacked_any

        # 8. 后续轮次：保持原有单队伍多轮循环逻辑。
        #    每队第 1 轮已由上方批量派出，故从第 2 轮继续。
        for t_idx, tgt in enumerate(target_teams, 1):
            if should_stop and should_stop():
                break
            # 轮前清理可能已弹出的战败弹窗（上一队后续轮次战斗可能已失败）
            if has_result_popup(engine):
                dismiss_result(engine)
                if on_progress:
                    on_progress("轮前检测到战败弹窗，已关闭")
            if on_progress:
                on_progress(
                    f"【队伍 {t_idx}/{len(target_teams)}】攻打 {tgt['name']}")
            ok = attack_with_team(
                engine, loc, tgt, on_progress, should_stop,
                start_round=2)
            if ok:
                attacked_any = True
            if should_stop and should_stop():
                break

        return attacked_any

    except Exception as e:  # noqa: BLE001
        logger.exception("攻打异常 %s", loc.name)
        engine.report["errors"].append(f"攻打{loc.name}异常: {e}")
        return False


def attack_with_team(engine, loc: BattleLocation, target: dict,
                     on_progress=None, should_stop=None,
                     start_round: int = 1) -> bool:
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

    for round_no in range(start_round, engine.max_attacks_per_loc + 1):
        if should_stop and should_stop():
            break

        # 0. 轮前清理战败弹窗
        if has_result_popup(engine):
            dismiss_result(engine)
            defeat_count += 1
            if on_progress:
                on_progress(
                    f"【第{round_no}轮】战斗失败（第{defeat_count}次），"
                    f"已关闭战败弹窗")
            if sleep_interruptible(2.0, should_stop):
                break

        # 1. 重新导航：从大地图→情报→城池战事→定位城市→点攻城
        ok = open_attack_panel_for_city(
            engine, loc, on_progress, should_stop)
        if not ok:
            if on_progress:
                on_progress(
                    f"【第{round_no}轮】打开攻打面板失败，结束：{loc.name}")
            break

        # 2. 解析队伍面板
        teams = parse_team_panel(engine, on_progress)
        if not teams:
            if on_progress:
                on_progress(
                    f"【第{round_no}轮】未读取到队伍面板，结束：{loc.name}")
            back_to_world_map(engine, on_progress)
            break

        target = find_team_by_name(engine, teams, team_name)
        if not target and team_index and team_index <= len(teams):
            target = teams[team_index - 1]
        if not target:
            if on_progress:
                on_progress(
                    f"【第{round_no}轮】未找到目标队伍『{team_name}』，"
                    f"结束：{loc.name}")
            back_to_world_map(engine, on_progress)
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
                back_to_world_map(engine, on_progress)
                break
            # 自己派出去的，继续等
            if on_progress:
                on_progress(
                    f"【第{round_no}轮】队伍出征中（{status}），等待返回")

        # 4. 重伤 / 恢复中：等恢复倒计时结束再打，不在重伤期点攻打
        #    （点了也派不出，本就不该计入成功轮次）。补兵救不了重伤，
        #    原地等待恢复后进入下一轮重试。恢复完成前本轮不攻打、不计成功。
        if not target.get("attackable", True):
            inj_secs = parse_injury_wait(engine, target)
            # 有明确倒计时 → 等它；无倒计时给保守默认，避免无限空转也避免堵死
            wait_secs = inj_secs if inj_secs > 0 else 60
            if wait_secs > 300:
                wait_secs = 300
            if on_progress:
                on_progress(
                    f"【第{round_no}轮】队伍重伤/恢复中，"
                    f"等待恢复约 {wait_secs} 秒后重试：{team_name}")
            if sleep_interruptible(wait_secs, should_stop):
                break
            # 等待后重新解析面板，确认是否已恢复；本轮不攻打、不计成功轮次
            teams = parse_team_panel(engine, on_progress)
            target = find_team_by_name(engine, teams, team_name)
            if not target and team_index:
                teams2 = parse_team_panel(engine, on_progress)
                if team_index <= len(teams2):
                    target = teams2[team_index - 1]
            if not target:
                if on_progress:
                    on_progress(
                        f"【第{round_no}轮】恢复等待后找不到队伍，"
                        f"结束：{team_name}")
                back_to_world_map(engine, on_progress)
                break
            team_name = target.get("name", team_name)
            continue

        # 5. 补兵：每轮战斗前点面板底部『一键补兵』大按钮（给全部队伍补兵）。
        # 兵满时点了也无副作用，无需通过血条颜色验证。
        # 无粮情况由 _has_no_food 检测兜底，真没兵则点攻打时 toast 也会拦截。
        if on_progress:
            on_progress(f"【第{round_no}轮】一键补兵：{team_name}")
        clicked = click_supply_all_btn(engine, on_progress)
        if not clicked:
            if on_progress:
                on_progress("未找到一键补兵按钮，跳过补兵直接攻打")
        else:
            if sleep_interruptible(1.5, should_stop):
                break
            if has_no_food(engine):
                engine._food_exhausted = True
                if on_progress:
                    on_progress(
                        f"补兵失败（无粮食），结束攻打：{team_name}")
            back_to_world_map(engine, on_progress)
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
            click_attack_btn_on_team(engine, target, on_progress)
            if sleep_interruptible(3.0, should_stop):
                break

            if has_toast(
                engine, UNAVAILABLE_KEYWORDS,
                template="zhan_gong_unavailable.png",
            ):
                if on_progress:
                    on_progress(
                        f"攻打失败（血量不足/无法攻打提示），"
                        f"放弃：{team_name}")
                back_to_world_map(engine, on_progress)
                return attacked_any

            # 关面板回大地图，验证是否真的出征
            back_to_world_map(engine, on_progress)
            if sleep_interruptible(3.0, should_stop):
                break

            if verify_team_marching(engine, team_name):
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
            ok = open_attack_panel_for_city(
                engine, loc, on_progress, should_stop)
            if not ok:
                break
            click_supply_all_btn(engine, on_progress)
            if sleep_interruptible(2.0, should_stop):
                break
            teams = parse_team_panel(engine, on_progress)
            target = find_team_by_name(engine, teams, team_name)
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
        stopped, final_status = wait_battle_return(
            engine, loc, target, on_progress, should_stop)
        if stopped:
            break

    # 保存战败统计
    if defeat_count > 0:
        engine.report["defeat_count"] = (
            engine.report.get("defeat_count", 0) + defeat_count)

    return attacked_any


# ---------------------------------------------------------------- 战斗等待

def wait_battle_end(engine, on_progress=None, should_stop=None) -> bool:
    """等待战斗结束（固定等待 + 轮询判断结果弹窗）。

    返回 True 表示停止被请求（应中断整个攻打流程）。
    """
    # 战斗动画 + 结算，先固定等待
    if sleep_interruptible(3.0, should_stop):
        return True
    # 轮询一段时间，直到出现结果弹窗或超时
    deadline = time.time() + 60
    while time.time() < deadline:
        if should_stop and should_stop():
            return True
        if has_result_popup(engine):
            return False
        if sleep_interruptible(1.0, should_stop):
            return True
    if on_progress:
        on_progress("等待战斗结果超时，继续")
    return False


def wait_battle_return(engine, loc: BattleLocation, target: dict,
                       on_progress=None, should_stop=None) -> tuple[bool, str]:
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
    back_to_world_map(engine, on_progress)
    if sleep_interruptible(2.0, should_stop):
        return True, "?"

    last_status = "出征中"
    while time.time() < deadline:
        if should_stop and should_stop():
            return True, last_status

        # 1. 优先检测战败弹窗
        if has_result_popup(engine):
            dismiss_result(engine)
            if on_progress:
                on_progress("检测到战败弹窗，已关闭")
            if sleep_interruptible(3.0, should_stop):
                return True, "战败"
            continue

        # 2. 用大地图常驻队伍列表（compact）检测状态
        try:
            teams = parse_team_panel(engine, compact=True)
        except Exception as e:  # noqa: BLE001
            logger.debug("等待战斗中队伍列表解析失败: %s", e)
            teams = []

        if teams:
            t = find_team_by_name(engine, teams, team_name, target)
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
        if sleep_interruptible(poll_interval, should_stop):
            return True, last_status

    if on_progress:
        on_progress(
            f"等待战斗结束超时（{total_timeout}s），"
            f"队伍『{team_name}』状态：{last_status}")
    return False, "超时"


def wait_battle_return_multi(engine, loc: BattleLocation,
                             targets: list[dict],
                             on_progress=None, should_stop=None) -> bool:
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
        if has_result_popup(engine):
            dismiss_result(engine)
            if on_progress:
                on_progress("检测到战败弹窗，已关闭")
            if sleep_interruptible(3.0, should_stop):
                return True
            continue

        # 2. 用大地图常驻队伍列表（compact）检测各队状态
        try:
            teams = parse_team_panel(engine, compact=True)
        except Exception as e:  # noqa: BLE001
            logger.debug("等待战斗中队伍列表解析失败: %s", e)
            teams = []

        if teams:
            done = []
            for name in pending:
                t = find_team_by_name(engine, teams, name)
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
        if sleep_interruptible(poll_interval, should_stop):
            return True

    if pending and on_progress:
        on_progress(
            f"等待战斗结束超时（{total_timeout}s），"
            f"尚未结束的队伍：{pending}")
    return False