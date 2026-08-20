"""纯逻辑工具函数（无 ctrl 调用）。原样搬运。"""

import re
import time


def to_int(s: str) -> int:
    try:
        return int(s.replace(",", "").replace("，", ""))
    except ValueError:
        return 0


def parse_troop_number(text: str) -> int:
    """解析队伍数量。支持："33" / "29+86"（驻守+增援）。"""
    text = text.strip()
    if not text:
        return 0
    # 29+86 → 115
    if "+" in text:
        total = 0
        for part in text.split("+"):
            total += to_int(part)
        return total
    return to_int(text)


def clean_city_name(text: str) -> str:
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


def is_nanman_city(name: str) -> bool:
    """判断城市名是否属于南蛮入侵活动（南蛮率众攻城）。

    南蛮活动期间，战斗地点会带『南蛮』前缀（如「南蛮 某城」）。
    由于 clean_city_name 只清理 吴/蜀/魏 前缀，南蛮前缀会保留在 loc.name 里。
    仅在名字里含『南蛮』（或整词『蛮族』）时判定为南蛮，避免『武蛮/蛮荒』等误判。
    """
    if not name:
        return False
    return "南蛮" in name or "蛮族" in name


def parse_time_text(text: str) -> int:
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


def is_green(r: int, g: int, b: int) -> bool:
    """判断是否为绿血条像素（RGB(62,203,98) 附近）。"""
    return g > 120 and g > r * 1.6 and g > b * 1.6


def sleep_interruptible(
    seconds: float,
    should_stop=None,
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