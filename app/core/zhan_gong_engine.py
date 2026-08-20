"""战功引擎旧入口（兼容 shim）。

历史 import 路径 `from app.core.zhan_gong_engine import ...` 不再破坏：
本文件原为此处唯一的 2716 行单体引擎，现已被拆分为 `app.core.zhan_gong` 包。
此处仅对包内容做 re-export，保持 `app.core.zhan_gong_engine` 路径可继续 import。
无任何新逻辑。
"""
from app.core.zhan_gong.engine import ZhanGongEngine
from app.core.zhan_gong.model import BattleLocation  # noqa: F401

__all__ = ["ZhanGongEngine", "BattleLocation"]