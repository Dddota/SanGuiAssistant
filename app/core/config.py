"""全局运行配置。

连接参数默认值在此定义；用户可在"设置"Tab 中修改并通过 QSettings 持久化，
运行时会优先读取持久化值。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt6.QtCore import QSettings

APP_NAME = "sangui-ass"
ORG_NAME = "sangui"

ADB_PATH = r"E:\GAME\MuMu Player 12\shell\adb.exe"
ADB_ADDRESS = "127.0.0.1:16384"

# 常见模拟器 adb 候选路径（按优先级探测）
_ADB_CANDIDATES = [
    r"E:\GAME\MuMu Player 12\shell\adb.exe",
    r"C:\Program Files\Netease\MuMu Player 12\shell\adb.exe",
    r"D:\Program Files\Netease\MuMu Player 12\shell\adb.exe",
    r"C:\Program Files\Netease\MuMu\emulator\nemu\vmonitor\bin\adb_server.exe",
    r"C:\Program Files\Netease\MuMu\emulator\nemu\vmonitor\bin\adb.exe",
    r"C:\LDPlayer\LDPlayer9\adb.exe",
    r"D:\LDPlayer\LDPlayer9\adb.exe",
    r"C:\Program Files\LDPlayer\LDPlayer9\adb.exe",
    r"C:\Program Files (x86)\Nox\bin\adb.exe",
    r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
    r"C:\Program Files\Microvirt\MEmu\adb.exe",
    r"C:\Program Files\Tencent\MobileGamePC\adb.exe",
]


def detect_adb() -> str:
    """自动探测本机可用的 adb.exe。

    依次检查常见模拟器安装路径与 PATH 环境变量，返回第一个存在的；
    全部未命中时回退到默认 ADB_PATH。
    """
    for cand in _ADB_CANDIDATES:
        if Path(cand).is_file():
            return cand
    for dir_ in os.environ.get("PATH", "").split(os.pathsep):
        if not dir_:
            continue
        exe = Path(dir_) / "adb.exe"
        if exe.is_file():
            return str(exe)
    return ADB_PATH


def app_root() -> Path:
    """应用资源根目录（含 `assets` 顶层目录所在处）。

    - PyInstaller 打包运行时：取 exe 所在目录（发布包内 resources 放 exe 旁）。
    - 源码/开发运行：取项目根目录（assets 位于 project/ 下的 app/assets）。
    """
    if getattr(sys, "frozen", False):  # PyInstaller 打包的 exe
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def assets_root() -> Path:
    """`app/assets` 目录路径。

    - 打包运行时：<exe 目录>/app/assets（发布时与 exe 一起打包）。
    - 源码运行：<项目根>/app/assets。
    """
    return app_root() / "app" / "assets"


RESOURCE_PATH = str(assets_root())


def settings() -> QSettings:
    return QSettings(ORG_NAME, APP_NAME)


def get_connection_params() -> dict:
    """读取持久化的连接参数，未保存过时返回默认值。

    若持久化的 adb 路径已失效（文件不存在），自动回退到 detect_adb() 探测结果。
    """
    s = settings()
    adb_path = s.value("adb_path", "", str)
    if not adb_path or not Path(adb_path).is_file():
        adb_path = detect_adb()
    return {
        "adb_path": adb_path,
        "address": s.value("address", ADB_ADDRESS, str),
        "resource_path": s.value("resource_path", RESOURCE_PATH, str),
    }


def save_connection_params(adb_path: str, address: str, resource_path: str) -> None:
    """持久化连接参数。"""
    s = settings()
    s.setValue("adb_path", adb_path)
    s.setValue("address", address)
    s.setValue("resource_path", resource_path)
    s.sync()


# ---------------- 界面/任务状态持久化 ----------------

def get_selected_tasks() -> list[str]:
    """读取上次勾选的任务 key 列表。"""
    s = settings()
    return s.value("selected_tasks", [], type=list)


def save_selected_tasks(keys: list[str]) -> None:
    """持久化勾选的任务 key 列表。"""
    s = settings()
    s.setValue("selected_tasks", list(keys))
    s.sync()


def get_last_task() -> str:
    """读取上次打开/选中的任务 key。"""
    s = settings()
    return s.value("last_task", "", str)


def save_last_task(key: str) -> None:
    """持久化上次打开/选中的任务 key。"""
    s = settings()
    s.setValue("last_task", key)
    s.sync()


def get_zg_city_list() -> list[dict]:
    """读取战功地点列表（含勾选状态）。"""
    s = settings()
    names = s.value("zg_city_names", [], type=list)
    checked = set(s.value("zg_city_checked", [], type=list))
    return [{"name": n, "checked": n in checked} for n in names]


def save_zg_city_list(cities: list[dict]) -> None:
    """持久化战功地点列表（含勾选状态）。"""
    s = settings()
    s.setValue("zg_city_names", [c["name"] for c in cities])
    s.setValue("zg_city_checked", [c["name"] for c in cities if c["checked"]])
    s.sync()


def get_zg_ratio() -> float:
    s = settings()
    return s.value("zg_ratio", 2.0, float)


def save_zg_ratio(v: float) -> None:
    s = settings()
    s.setValue("zg_ratio", v)
    s.sync()


def get_zg_max_time() -> int:
    s = settings()
    return s.value("zg_max_time", 600, int)


def save_zg_max_time(v: int) -> None:
    s = settings()
    s.setValue("zg_max_time", v)
    s.sync()