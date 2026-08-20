"""全部任务结束后的收尾动作（参照明日方舟 MAA，多选）。"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Callable, Optional

from app.core import config

logger = logging.getLogger("sangui.post_action")

# (取值, 中文标签) — 原子可勾选项，顺序即复选框顺序
POST_ACTIONS = [
    ("close_emulator", "关闭模拟器"),
    ("quit", "退出三归小助手"),
    ("shutdown", "关机"),
]


def label_of(key: str) -> str:
    for k, label in POST_ACTIONS:
        if k == key:
            return label
    return key


def close_emulator(log: Optional[Callable[[str], None]] = None) -> None:
    """通过 adb 优雅关闭当前模拟器。"""
    if log:
        log("正在关闭模拟器...")
    params = config.get_connection_params()
    adb = params["adb_path"]
    addr = params["address"]
    if not adb or not Path(adb).is_file():
        if log:
            log("未找到 adb，无法关闭模拟器")
        return
    try:
        subprocess.run([adb, "-s", addr, "emu", "kill"],
                       timeout=15, capture_output=True)
        if log:
            log("已发送关闭模拟器指令")
    except Exception as e:  # noqa: BLE001
        logger.exception("Close emulator failed")
        if log:
            log(f"关闭模拟器失败：{e}")


def remote_shutdown(log: Optional[Callable[[str], None]] = None) -> None:
    """Windows 延时关机。"""
    if log:
        log("60 秒后关机（可取消）...")
    try:
        subprocess.run(["shutdown", "/s", "/t", "60"],
                       timeout=10, capture_output=True)
    except Exception as e:  # noqa: BLE001
        logger.exception("Shutdown failed")
        if log:
            log(f"发起关机失败：{e}")


def remote_shutdown_abort(log: Optional[Callable[[str], None]] = None) -> None:
    """取消 Windows 延时关机（shutdown /a）。"""
    try:
        subprocess.run(["shutdown", "/a"],
                       timeout=10, capture_output=True)
        if log:
            log("已取消关机")
    except Exception as e:  # noqa: BLE001
        logger.exception("Cancel shutdown failed")
        if log:
            log(f"取消关机失败：{e}")


def execute(actions,
            quit_app: Optional[Callable[[], None]] = None,
            log: Optional[Callable[[str], None]] = None) -> None:
    """执行收尾动作集合。actions 为键组成的可迭代对象，已过滤 none。
    quit 相关在末尾调用一次 quit_app。可能含阻塞 subprocess，调用方在后台线程调。
    """
    acts = [a for a in actions if a in dict(POST_ACTIONS)]
    if not acts:
        return
    for act in acts:
        if act == "close_emulator":
            close_emulator(log)
        elif act == "shutdown":
            remote_shutdown(log)
    if "quit" in acts:
        if quit_app is not None:
            if log:
                log("正在退出三归小助手...")
            quit_app()