"""报告聚合与保存。原样搬运。"""

import json
import logging
from datetime import datetime
from pathlib import Path

from .model import BattleLocation

logger = logging.getLogger("sangui.zhangong")


def loc_to_report(engine, loc: BattleLocation, attacked: bool = False) -> dict:
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


def dump_params(engine) -> dict:
    """把引擎当前参数快照为报告用 dict。"""
    return {
        "list_roi": list(engine.list_roi),
        "team_panel_roi": list(engine.team_panel_roi),
        "toast_roi": list(engine.toast_roi),
        "wait_anim": engine.wait_anim,
        "max_cost_time": engine.max_cost_time,
        "priority_cities": engine.priority_cities,
        "max_attacks": engine.max_attacks,
        "max_locations": engine.max_locations,
        "max_attacks_per_loc": engine.max_attacks_per_loc,
        "max_scrolls": engine.max_scrolls,
        "scroll_idle_limit": engine.scroll_idle_limit,
        "scroll_step": engine.scroll_step,
        "team_name": engine.team_name,
        "team_index": engine.team_index,
        "team_names": engine.team_names,
    }


def save_report(engine, path: str | Path | None = None) -> str:
    """保存诊断报告为 JSON，返回文件路径。"""
    from app.utils.logger import LOG_DIR
    out_dir = Path(path) if path else LOG_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fpath = out_dir / f"zhan_gong_{ts}.json"
    fpath.write_text(
        json.dumps(engine.report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("ZhanGong report saved: %s", fpath)
    return str(fpath)