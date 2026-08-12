"""全局运行配置。

连接参数默认值在此定义；用户可在"设置"Tab 中修改并通过 QSettings 持久化，
运行时会优先读取持久化值。
"""
from __future__ import annotations

from PyQt6.QtCore import QSettings

APP_NAME = "sangui-ass"
ORG_NAME = "sangui"

ADB_PATH = r"E:\GAME\MuMu Player 12\shell\adb.exe"
ADB_ADDRESS = "127.0.0.1:16384"
RESOURCE_PATH = "app/assets"


def settings() -> QSettings:
    return QSettings(ORG_NAME, APP_NAME)


def get_connection_params() -> dict:
    """读取持久化的连接参数，未保存过时返回默认值。"""
    s = settings()
    return {
        "adb_path": s.value("adb_path", ADB_PATH, str),
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