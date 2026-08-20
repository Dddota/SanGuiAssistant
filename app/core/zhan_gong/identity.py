"""角色身份探测：仅探测角色名（区服在 1280x720 大地图上无法可靠 OCR，不探测）。

命名空间约定：默认 identity = 清洗后的角色名；用户可手动设置『角色备注/别名』，
设置后 identity 命名空间改用别名（见 app/core/config.py 的 role_namespace），
用于区分不同账号下同名角色导致的配置撞车。
"""
from __future__ import annotations

import logging
import re

from .navigation import is_on_world_map

logger = logging.getLogger("sangui.zhangong.identity")

# 角色名 ROI：屏幕上角色名出现的区域（粗略左上角）。1280x720 下默认取左上角一小块，
# 后续由用户截图校准精确值（调整此常量即可，无需改逻辑）。
# 1280x720 大地图左上角：头像右侧、角色名所在的文本行。
# 由世界地图截图校准：头像约 x 5-55，角色名文本行约 y 6-34，
# 右侧"民心"图标和下方战力数字均排除，减少 OCR 噪音。
ROLE_NAME_ROI = (58, 6, 140, 30)

# 角色名里应忽略的常见噪音（UI 元件/重复文本）
_NOISE = {
    "我的", "个人", "角色", "信息", "头像", "等级", "战力",
    "装备", "设置", "任务", "邮件", "公告", "返回", "排行榜",
    "头像框", "改名", "礼包", "活动", "商店",
}


def _probe_role_text(ctrl) -> str | None:
    """在 ROLE_NAME_ROI 内 OCR，返回最像角色名的候选（去掉噪音）。"""
    try:
        results = ctrl.ocr(ROLE_NAME_ROI)
    except Exception as e:  # noqa: BLE001
        logger.debug("角色名 OCR 失败: %s", e)
        return None
    if not results:
        return None

    best = None
    best_len = 0
    for r in results:
        text = (r.get("text") or "").strip()
        if not text:
            continue
        # 去掉常见的纯符号/纯数字（角色名含中文）
        if not any('\u4e00' <= c <= '\u9fff' for c in text):
            continue
        if len(text) < 2:
            continue
        # 取最长的有效中文文本作为候选（OCR 常把角色名断词）
        if len(text) > best_len:
            best = text
            best_len = len(text)

    if not best:
        return None

    # 去掉结尾的纯数字/等级等尾部噪声（如"诸葛亮12"）
    m = re.search(r"^([\u4e00-\u9fa5]{2,})", best)
    if not m:
        return None
    name = m.group(1)
    if name in _NOISE:
        return None
    return name


def probe_identity(ctrl, on_progress=None) -> dict | None:
    """探测当前角色身份。

    仅在确认位于大地图时才信任 OCR（避免在加载/战斗等非大地图界面误判）。
    返回 {"role": str, "confidence": float}；无法确定时返回 None（无服务端校验）。
    """
    try:
        # 先确认在大地图，否则不信任 OCR 结果（不强制导航用户界面）
        if not is_on_world_map(ctrl):
            if on_progress:
                on_progress("未检测到大地图，跳过角色身份探测")
            return None
        role = _probe_role_text(ctrl)
    except Exception as e:  # noqa: BLE001
        logger.warning("角色身份探测失败: %s", e)
        return None

    if not role:
        if on_progress:
            on_progress("未能从大地图识别角色名")
        return None

    if on_progress:
        on_progress(f"识别到角色：{role}")
    # 本地 OCR 命中但无服务端校验，信心度固定给一个可用默认值
    return {"role": role, "confidence": 0.7}