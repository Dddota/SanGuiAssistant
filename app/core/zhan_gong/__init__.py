"""战功引擎包。门面在 engine.py，此处 re-export 保持旧 import 兼容。

旧 import 路径 `from app.core.zhan_gong_engine import ...` 由
`app/core/zhan_gong_engine.py` 兜底适配（见该文件）。
此处同时暴露包内模块级 API 供 `from app.core.zhan_gong import ZhanGongEngine` 使用。
"""
from .engine import ZhanGongEngine
from .model import BattleLocation  # noqa: F401

__all__ = ["ZhanGongEngine", "BattleLocation"]