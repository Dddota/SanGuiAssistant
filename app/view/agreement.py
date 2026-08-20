"""首次启动用户协议确认。

在展示主窗口前，于栈顶弹出协议对话框，要求用户阅读并同意
TERMS_OF_SERVICE.md 后才能继续使用；拒绝则退出程序。
同意后记录到 QSettings，后续启动不再重复弹出。
"""
from __future__ import annotations

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QDialog, QMessageBox, QDialogButtonBox, QTextEdit, QVBoxLayout, QLabel

from app.core.config import app_root

# 本地记忆键：记录已同意的用户协议版本
_ACCEPT_KEY = "agreement/accepted_version"
# 依赖 TERMS_OF_SERVICE.md 顶部的版本行，改动版本号即可要求用户重新确认
PROTOCOL_VERSION = "2026-08-20"


def _agreement_text() -> str:
    """读取仓库根目录的 TERMS_OF_SERVICE.md 全文；缺失时给出兜底文案。"""
    path = app_root() / "TERMS_OF_SERVICE.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return (
            "《三归小助手》用户协议\n\n"
            "本工具仅供学习交流使用，不用于任何商业代练、打金、账号交易等盈利性活动。\n"
            "用户需自行承担使用本工具的一切风险与后果，包括账号封禁等。\n"
            "本工具与游戏厂商《三国天下归心》（恺英网络）无任何关联。\n"
        )


def has_accepted() -> bool:
    """判断当前环境是否已同意过当前版本协议。"""
    s = QSettings("sangui", "sangui-ass")
    return s.value(_ACCEPT_KEY, "", str) == PROTOCOL_VERSION


def confirm_agreement() -> bool:
    """展示协议确认对话框。返回 True 表示用户同意，False 表示拒绝/关闭。

    仅当尚未同意当前版本协议时才会真正弹窗。
    """
    if has_accepted():
        return True

    dlg = QDialog()
    dlg.setWindowTitle("用户协议")
    dlg.resize(680, 620)

    lay = QVBoxLayout(dlg)
    tip = QLabel(
        "开始使用即表示您已满 18 周岁（或法定监护人代为同意），"
        "并已完整阅读、充分理解且同意遵守《三归小助手》用户协议的全部条款。"
    )
    tip.setWordWrap(True)
    lay.addWidget(tip)

    viewer = QTextEdit(dlg)
    viewer.setReadOnly(True)
    viewer.setPlainText(_agreement_text())
    lay.addWidget(viewer, 1)

    btns = QDialogButtonBox(dlg)
    agree = btns.addButton("同意并继续", QDialogButtonBox.ButtonRole.AcceptRole)
    btns.addButton("不同意，退出", QDialogButtonBox.ButtonRole.RejectRole)
    lay.addWidget(btns)

    btns.accepted.connect(dlg.accept)
    btns.rejected.connect(dlg.reject)

    if dlg.exec() != QDialog.DialogCode.Accepted or not agree.isEnabled():
        return False

    # 同意则本地记忆，避免下次启动重复弹窗
    QSettings("sangui", "sangui-ass").setValue(_ACCEPT_KEY, PROTOCOL_VERSION)
    return True


def need_agreement_retry_or_quit() -> bool:
    """协议未通过时提示并退出；返回是否继续（当前仅作退出通知）。"""
    QMessageBox.warning(
        None,
        "未同意用户协议",
        "您未同意《三归小助手》用户协议，程序即将退出。",
    )
    return False