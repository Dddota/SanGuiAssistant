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
    全部未命中时返回空字符串，让上层明确报错而不是回退到无效的硬编码路径。
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
    return ""


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


# ---------------- 角色身份 / 命名空间 ----------------

_ZNOW: str = ""  # 进程内当前角色身份（进程级访问器状态，非持久化最新值）
_LEGACY_MIGRATED_KEY = "zg/legacy_migrated"  # 一次性迁移标记


def sanitize_identity(identity: str) -> str:
    """角色命名空间清洗：去掉 `/`、`|`、控制字符，其余非法字符映射为 `_`。

    用于 `zg/roles/<identity>/...` 键的分段，保证写入 QSettings 安全。
    """
    if not identity:
        return "_unknown"
    out = []
    for ch in identity:
        code = ord(ch)
        if ch in "/|" or code < 32 or code == 127:
            continue
        if (ch.isalnum() or ch == "_" or ch == "-" or ch == "."
                or '\u4e00' <= ch <= '\u9fff'):
            out.append(ch)
        else:
            out.append("_")
    cleaned = "".join(out).strip()
    return cleaned or "_unknown"


def _role_key(identity: str, sub: str) -> str:
    return f"zg/roles/{sanitize_identity(identity)}/{sub}"


def set_current_identity(identity: str) -> None:
    """设置进程级当前角色身份，并持久化到 `zg/last_identity`。"""
    global _ZNOW
    sanitized = sanitize_identity(identity)
    _ZNOW = sanitized if sanitized != "_unknown" else identity
    s = settings()
    s.setValue("zg/last_identity", sanitized)
    s.sync()


def current_identity() -> str:
    """进程级当前角色身份（首次调用时从持久化的 last_identity 读取）。"""
    global _ZNOW
    if _ZNOW:
        return _ZNOW
    s = settings()
    last = s.value("zg/last_identity", "", str)
    if last:
        _ZNOW = last
        return last
    return ""


def set_role_alias(identity: str, alias: str) -> None:
    """为该角色设置可选别名（用于替代角色名作为身份命名空间，解决同名撞车）。"""
    s = settings()
    alias = (alias or "").strip()
    s.setValue(_role_key(identity, "alias"), alias)
    s.sync()


def get_role_alias(identity: str) -> str:
    s = settings()
    return s.value(_role_key(identity, "alias"), "", str)


def role_namespace(identity: str) -> str:
    """返回该角色应使用的身份命名空间：别名优先，否则角色名。"""
    alias = get_role_alias(identity)
    if alias:
        return sanitize_identity(alias)
    return sanitize_identity(identity)


# ---------------- 角色作用域战功配置 ----------------

def migrate_legacy_zg_config(identity: str) -> None:
    """一次性迁移旧扁平键到新角色命名空间。

    当旧扁平键（zg_city_names/zg_city_checked/zg_max_time）非空且
    目标角色键尚未写入时，把旧值播种到该角色下，然后清空旧键并打迁移标记。
    幂等防御：迁移标记已置或旧键已清空时不再执行。
    """
    s = settings()
    if s.value(_LEGACY_MIGRATED_KEY, False, bool):
        return
    leg_names = s.value("zg_city_names", [], type=list)
    leg_checked = s.value("zg_city_checked", [], type=list)
    has_legacy = bool(leg_names) or bool(leg_checked) or \
        s.contains("zg_max_time")
    if not has_legacy:
        s.setValue(_LEGACY_MIGRATED_KEY, True)
        s.sync()
        return
    ns = role_namespace(identity)
    base = f"zg/roles/{sanitize_identity(ns)}"
    if not s.value(f"{base}/city_names", [], type=list):
        s.setValue(f"{base}/city_names", leg_names)
        s.setValue(f"{base}/city_checked", leg_checked)
        if s.contains("zg_max_time"):
            s.setValue(f"{base}/max_time", s.value("zg_max_time", 600, int))
    # 清空旧扁平键
    s.remove("zg_city_names")
    s.remove("zg_city_checked")
    s.remove("zg_max_time")
    s.setValue(_LEGACY_MIGRATED_KEY, True)
    s.sync()


def get_zg_city_list(identity: str) -> list[dict]:
    """读取指定角色的战功地点列表（含勾选状态）。"""
    migrate_legacy_zg_config(identity)
    s = settings()
    names = s.value(_role_key(role_namespace(identity), "city_names"), [], type=list)
    checked = set(s.value(_role_key(role_namespace(identity), "city_checked"), [], type=list))
    return [{"name": n, "checked": n in checked} for n in names]


def save_zg_city_list(identity: str, city_names: list[str],
                      city_checked: list[str]) -> None:
    """持久化指定角色的战功地点列表（含勾选状态）。"""
    s = settings()
    s.setValue(_role_key(role_namespace(identity), "city_names"), list(city_names))
    s.setValue(_role_key(role_namespace(identity), "city_checked"), list(city_checked))
    s.sync()


def get_zg_max_time(identity: str) -> int:
    migrate_legacy_zg_config(identity)
    s = settings()
    return s.value(_role_key(role_namespace(identity), "max_time"), 600, int)


def save_zg_max_time(identity: str, v: int) -> None:
    s = settings()
    s.setValue(_role_key(role_namespace(identity), "max_time"), int(v))
    s.sync()


def get_zg_max_attacks(identity: str) -> int:
    migrate_legacy_zg_config(identity)
    s = settings()
    return s.value(_role_key(role_namespace(identity), "max_attacks"), 20, int)


def save_zg_max_attacks(identity: str, v: int) -> None:
    s = settings()
    s.setValue(_role_key(role_namespace(identity), "max_attacks"), int(v))
    s.sync()


def save_role_teams(identity: str, team_names: list[str]) -> None:
    """持久化某角色勾选/读到的出战队伍名列表。"""
    s = settings()
    s.setValue(_role_key(role_namespace(identity), "team_names"),
               [n for n in team_names if n])
    s.sync()


def get_role_teams(identity: str) -> list[str]:
    s = settings()
    return s.value(_role_key(role_namespace(identity), "team_names"), [], type=list)


def save_role_plan(identity: str, plan: dict) -> None:
    """持久化某角色的攻打计划 dict（Phase 3 消费）。"""
    s = settings()
    s.setValue(_role_key(role_namespace(identity), "plan"), dict(plan or {}))
    s.sync()


def get_role_plan(identity: str) -> dict | None:
    s = settings()
    plan = s.value(_role_key(role_namespace(identity), "plan"), None)
    if isinstance(plan, dict):
        return plan
    return None


def save_role_priority_address(identity: str, addr: str) -> None:
    """持久化某角色的优先级地址（Phase 3 消费）。"""
    s = settings()
    s.setValue(_role_key(role_namespace(identity), "priority_address"),
               (addr or "").strip())
    s.sync()


def get_role_priority_address(identity: str) -> str:
    s = settings()
    return s.value(_role_key(role_namespace(identity), "priority_address"), "", str)


# ---------------- 任务结束收尾动作（多选） ----------------
def get_post_actions() -> list[str]:
    """返回勾选集合。优先读新键 post_actions（列表）；回退旧单值键 post_action。"""
    s = settings()
    actions = s.value("post_actions", None, list)
    if actions is None:
        # 旧版单值回退
        single = s.value("post_action", "", str)
        return [single] if single and single != "none" else []
    return [a for a in actions if isinstance(a, str) and a and a != "none"]


def save_post_actions(actions: list[str]) -> None:
    s = settings()
    s.setValue("post_actions", [a for a in actions if a and a != "none"])
    s.setValue("post_action", "none")  # 兼容旧读取路径
    s.sync()


# 旧版单值接口（保留以兼容他处引用，内部委托到新模型）
def get_post_action() -> str:
    s = settings()
    return s.value("post_action", "none", str)


def save_post_action(action: str) -> None:
    s = settings()
    s.setValue("post_action", (action or "none"))
    s.sync()