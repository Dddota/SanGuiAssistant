"""队伍面板解析、卡片解析、补兵需求检测、目标队伍查找。原样搬运。"""

import logging
import re

from .constants import (
    TEAM_NAME_NOISE,
    TEAM_NAME_PREFIX_NOISE,
    TEAM_STATUS_NOISE,
    PANEL_RIGHT_X,
    ATTACK_BTN_DX_FROM_RIGHT,
    SUPPLY_BTN_DX_FROM_RIGHT,
    ATTACK_BTN_Y_OFFSET,
)
from .util import is_green, parse_time_text

logger = logging.getLogger("sangui.zhangong")


def read_my_teams(engine, on_progress=None) -> list[dict]:
    """读取大地图右侧常驻队伍列表，返回队伍字典列表。

    大地图队伍列表是紧凑布局（每行约 75px，2 行文字），使用 compact 模式解析。
    """
    try:
        teams = parse_team_panel(engine, on_progress, compact=True)
        if on_progress:
            names = [t.get("name", "?") for t in teams]
            on_progress(f"读取到 {len(teams)} 支队伍：{'、'.join(names)}")
        return teams
    except Exception as e:  # noqa: BLE001
        logger.exception("读取队伍列表失败")
        if on_progress:
            on_progress(f"读取队伍列表失败：{e}")
        return []


def parse_team_panel(engine, on_progress=None,
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
        # compact（大地图"我的队伍"常驻列表）：用收窄的 my_teams_roi，
        # 避开左边大地图的民心/成都/元宝/兵法/司南等无关文本。
        # 非 compact（队伍卡片面板）：用位宽 team_panel_roi。
        use_roi = getattr(engine, "my_teams_roi", None) if compact else None
        roi = use_roi if use_roi else engine.team_panel_roi
        logger.debug("队伍面板 OCR roi=%s (compact=%s)", roi, compact)
        results = engine.ctrl.ocr(roi=roi)
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
    cards = group_into_cards(items, card_height=card_h)
    logger.debug("队伍面板 %d 张卡片: %s", len(cards),
                 [[it["text"] for it in card] for card in cards])

    teams = []
    for card in cards:
        team = parse_team_card(engine, card)
        if team:
            teams.append(team)

    # 重伤队伍队名为空时（重伤时队名被倒计时覆盖），用序号填充占位名
    # 确保队伍计数/序号正确，避免"邺城"等地点名被误作队名
    for idx, team in enumerate(teams, 1):
        if team.get("is_injured") and not team.get("name"):
            team["name"] = f"第{idx}队重伤中"

    # 血条检测：有兵=绿色，无兵=灰色 → 需要补兵
    mark_need_supply(engine, teams, compact=compact)
    return teams


def group_into_cards(items: list[dict],
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


def mark_need_supply(engine, teams: list[dict], compact: bool = False) -> None:
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
        img = engine.ctrl.screencap()
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
                if is_green(r, g, b):
                    green = True
                    break
            if green:
                break
        team["need_supply"] = not green
    return


def parse_team_card(engine, card: list[dict]) -> dict | None:
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
                injury_time = parse_time_text(t)
                if injury_time > 0:
                    break

    def _is_noise(t: str) -> bool:
        t = t.strip()
        # 直接命中噪音词表 → 噪音
        if t in TEAM_NAME_NOISE:
            return True
        # 状态词 → 噪音
        if t in TEAM_STATUS_NOISE:
            return True
        # 含"队"但"队"前是页签/UI词（我的/临时/剩余等）或非纯人名 → 噪音
        if "队" in t:
            before = t[:t.find("队")]
            if before in TEAM_NAME_PREFIX_NOISE:
                return True
            # 被抓取的队名必须能形成"X队"（X为2-3字人名）
            return not re.fullmatch(r"[\u4e00-\u9fa5]{2,3}", before)
        # 其他不含"队"的短文本：看是否在噪音词表/是否像人名
        return len(t) <= 1 or t in TEAM_NAME_NOISE

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
        if name_clean in TEAM_NAME_NOISE:
            return None
        if name_clean in TEAM_STATUS_NOISE:
            return None
        if "队" in name_clean:
            before_dui = name_clean[:name_clean.find("队")]
            if before_dui in TEAM_NAME_PREFIX_NOISE:
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
            cost = parse_time_text(t)
            if cost > 0:
                break
    if cost == 0 and not is_injured:
        for it in card:
            t = it["text"]
            if re.search(r"\d+分\d+秒", t) or re.search(r"\d+[:：]\d+", t):
                cost = parse_time_text(t)
                if cost > 0:
                    break
    team["cost_time"] = cost

    # 攻打/补兵按钮：图标按钮，OCR 无文字，用固定 x 坐标 + 卡片中部偏下 y
    # 依据 vision 校准（MuMu-20260814-025514-633.png）：攻打按钮在卡片顶部下方约 66px
    # （第一张卡顶部155 → 攻打按钮221），比卡片中心更可靠
    btn_y = card_top + ATTACK_BTN_Y_OFFSET
    team["attack_btn"] = (PANEL_RIGHT_X - ATTACK_BTN_DX_FROM_RIGHT, btn_y)
    team["supply_btn"] = (PANEL_RIGHT_X - SUPPLY_BTN_DX_FROM_RIGHT, btn_y)

    return team


def find_target_team(engine, teams: list[dict], on_progress=None) -> dict | None:
    """在队伍列表里找到目标队伍。优先按名称，失败则按序号。"""
    # 按名称匹配
    if engine.team_name:
        for idx, t in enumerate(teams, 1):
            if engine.team_name in t["name"] or t["name"] in engine.team_name:
                t["index"] = idx
                if on_progress:
                    on_progress(f"匹配队伍：{t['name']}")
                return t
        # 尝试模糊匹配（包含部分文字）
        for idx, t in enumerate(teams, 1):
            if any(c in t["name"] for c in engine.team_name if '\u4e00' <= c <= '\u9fff'):
                t["index"] = idx
                if on_progress:
                    on_progress(f"模糊匹配队伍：{t['name']}")
                return t
        if on_progress:
            on_progress(f"未找到名称匹配的队伍『{engine.team_name}』，改用第 {engine.team_index} 队")

    # 按序号
    if 1 <= engine.team_index <= len(teams):
        t = teams[engine.team_index - 1]
        t["index"] = engine.team_index
        if on_progress:
            on_progress(f"选择第 {engine.team_index} 队：{t['name']}")
        return t

    return None


def find_team_by_name(engine, teams: list[dict], name: str,
                      fallback: dict | None = None) -> dict | None:
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


def parse_injury_wait(engine, target: dict) -> int:
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