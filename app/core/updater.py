"""自动更新：检查 Gitee Release 最新版、下载 zip、交由独立更新脚本覆盖安装。

由于 PyInstaller onedir 主程序运行时其 exe 与关键 DLL 被占用，无法热替换，
更新流程采用『下载 + 解压到临时目录 + detached PowerShell 脚本接管』：

1. check_for_update()：同时匿名查 Gitee 与 GitHub `/releases/latest`，
   取版本更高者（同版本优先 Gitee，国内快），比对版本号，
   返回最新版信息（tag / 下载 URL / 发布说明），无可更新时返回 None。
2. apply_update(info)：下载 zip 到临时目录并解压，生成 updater ps1，
   以独立 PowerShell 进程启动（主程序随后可安全退出）；脚本等待主进程
   结束后用 robocopy 将新文件覆盖到安装目录，再重启新版本。

纯函数部分不依赖 Qt；UI 层通过 UpdateWorker（QObject + 信号）在后台线程调用。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from app import __version__  # 本地版本号
from app.core.config import app_root

logger = logging.getLogger("sangui.updater")

# 双源仓库与 API 常量（均为公开仓库，读取无需 token）
# Gitee = 国内下载快（你手动同步 zip）；GitHub = 由 Actions 自动产出，永远最新。
# 检查逻辑：取版本更高者；同版本优先 Gitee。
OWNER = "Dddota"
REPO = "SanGuiAssistant"
_GITEE_API = f"https://gitee.com/api/v5/repos/{OWNER}/{REPO}"
_GITEE_LATEST_URL = f"{_GITEE_API}/releases/latest"
_GITHUB_LATEST_URL = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"
_UA = "SanguiHelper-Updater/2.0"
_LATEST_TIMEOUT = 15
DOWNLOAD_CHUNK = 1 << 20  # 1 MiB
COPY_EXE_NAMES = ("SanguiHelper.exe",)


def parse_version(v: str | None) -> tuple:
    """把 'v1.2.3' / '1.0.0' / '1.0-demo' 归一为 (major, minor, patch) 元组用于比较。"""
    if not v:
        return (0, 0, 0)
    parts = re.findall(r"\d+", v)
    nums = [int(p) for p in parts[:3]]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def _request(url: str, timeout: int = _LATEST_TIMEOUT, headers: dict | None = None) -> bytes:
    headers = {"User-Agent": _UA, **(headers or {})}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_release(data: dict) -> dict:
    """把单个 Release 响应解析为统一结构，找不到二进制 zip 抛异常。

    注意：Gitee 会给每个 Release 自动生成 `{tag}.zip` / `{tag}.tar.gz`
    源码归档附件（按 tag 命名）。必须只认二进制发布包 `SanguiHelper-*.zip`，
    否则可能误把源码包当成更新包。
    """
    tag = data.get("tag_name", "")
    if not tag:
        raise RuntimeError("Release 缺少 tag_name")
    assets = data.get("assets") or data.get("attach_files") or []
    zip_asset = next(
        (
            a for a in assets
            if a.get("name", "").lower().endswith(".zip")
            and "sanguihelper" in a.get("name", "").lower()
        ),
        None,
    )
    if not zip_asset:
        raise RuntimeError(f"Release {tag} 中没有找到 SanguiHelper 二进制 zip 附件")
    return {
        "tag": tag,
        "name": zip_asset.get("name", ""),
        "download_url": zip_asset.get("browser_download_url", ""),
        "body": data.get("body", ""),
    }


def _latest_release_from(url: str, headers: dict | None = None) -> Optional[dict]:
    """从单个源拉取最新 Release。网络/解析错误抛异常。"""
    try:
        raw = _request(url, headers=headers)
        data = json.loads(raw.decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
        # 404 = 该源还没有 Release 或临时不可用，返回 None；其它异常上抛
        if isinstance(e, urllib.error.HTTPError) and e.code == 404:
            return None
        raise
    return _parse_release(data)


def _latest_release() -> Optional[dict]:
    """双源查最新：同时看 Gitee 与 GitHub，取版本更高者；同版本走 Gitee。

    返回统一结构（tag/name/download_url/body），或 None（都不可靠时）。
    单个源 404 视为"该源无 Release"；两源都失败时上抛最后一次异常。
    """
    gitee = github = None
    err = None
    for name, url, hdrs in (
        ("gitee", _GITEE_LATEST_URL, None),
        ("github", _GITHUB_LATEST_URL, {"Accept": "application/vnd.github+json"}),
    ):
        try:
            r = _latest_release_from(url, headers=hdrs)
            logger.info("check %s -> %s", name, (r or {}).get("tag"))
            if name == "gitee":
                gitee = r
            else:
                github = r
        except Exception as e:  # noqa: BLE001
            logger.warning("check %s failed: %s", name, e)
            err = e
    if gitee is None and github is None:
        if err:
            raise err  # 两源都不可用，向上抛
        return None
    # 同版本优先 Gitee（国内快）；否则取版本更高者
    if gitee and github:
        if parse_version(gitee["tag"]) == parse_version(github["tag"]):
            return gitee
        return gitee if parse_version(gitee["tag"]) > parse_version(github["tag"]) else github
    return gitee or github


def check_for_update() -> Optional[dict]:
    """比对线上最新版与本地版本：有更新返回 info，否则 None。

    网络异常 / 无 Release / 版本相同 均返回 None（不向用户报错），
    只有"发现更高版本"才返回 info。
    """
    try:
        latest = _latest_release()
    except Exception as e:  # noqa: BLE001
        logger.warning("check_for_update failed: %s", e)
        return None
    if parse_version(latest["tag"]) <= parse_version(__version__):
        return None
    latest["local_version"] = __version__
    return latest


def _download(url: str, dest: Path, on_chunk=None) -> None:
    """流式下载 url 到 dest，避免大面积内存占用。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(DOWNLOAD_CHUNK)
            if not chunk:
                break
            f.write(chunk)
            if on_chunk:
                on_chunk(len(chunk))


def _extract_zip(zip_path: Path, target: Path) -> None:
    """解压 zip 到 target。zip 根即发布内容（不含外层文件夹）。"""
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            # 防路径穿越
            dest = (target / member.filename).resolve()
            if not dest.is_relative_to(target.resolve()):
                raise RuntimeError(f"压缩包包含非法路径: {member.filename}")
        z.extractall(target)


def install_dir() -> Path:
    """发布包安装目录 = 当前 exe 所在目录（onedir 结构）。"""
    return app_root()


def _script_pause_ms() -> int:
    # 给主进程退出留缓冲
    return 2000


def _write_updater_script(info: dict, new_dir: Path, install: Path) -> Path:
    """生成并返回独立更新脚本路径（不执行）。

    脚本职责：等主进程退出 → robocopy 覆盖安装目录 → 重启新 exe → 清理临时目录。
    """
    pid = os.getpid()
    main_exe = (install / "SanguiHelper.exe").resolve()
    pause = _script_pause_ms()
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$mainExe = '{main_exe}'",
        f"$install = '{install}'",
        f"$newDir = '{new_dir}'",
        f"$pid0 = {pid}",
        f"Start-Sleep -Milliseconds {pause}",
        # 等待主进程（含已退出的竞态）结束
        "for ($i = 0; $i -lt 60; $i++) {",
        "    if (-not (Get-Process -Id $pid0 -ErrorAction SilentlyContinue)) { break }",
        "    Start-Sleep -Milliseconds 500",
        "}",
        # 覆盖安装：/E 递归空目录 /IS /IT 含相同与更旧文件 /PURGE 删除目标多余文件
        "& robocopy $newDir $install /E /IS /IT /PURGE /NFL /NDL /NJH /NJS /NP | Out-Null",
        "if ($LASTEXITCODE -ge 8) { throw 'robocopy 覆盖失败 (code ' + $LASTEXITCODE + ')' }",
        # 清理临时目录
        "if (Test-Path $newDir) { Remove-Item $newDir -Recurse -Force -ErrorAction SilentlyContinue }",
        # 重启新版本
        "Start-Process -FilePath $mainExe -WorkingDirectory $install",
    ]
    ps1 = Path(tempfile.gettempdir()) / "sangui_updater.ps1"
    ps1.write_text("\r\n".join(lines), encoding="utf-8")
    return ps1


def apply_update(info: dict, on_progress=None) -> None:
    """下载并应用更新：下载 → 解压 → 启动独立更新脚本。

    on_progress: Optional[Callable[[str], None]]，用于进度提示。
    本函数返回即表示"更新脚本已启动"，主程序应随后提示用户并自行退出。
    """
    workdir = Path(tempfile.gettempdir()) / "sangui_update"
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)

    if on_progress:
        on_progress("下载更新包...")
    zip_path = workdir / "package.zip"
    _download(info["download_url"], zip_path, on_chunk=None)

    if on_progress:
        on_progress("解压更新包...")
    new_dir = workdir / "new"
    _extract_zip(zip_path, new_dir)

    # zip 可能包含顶层文件夹；若根下只有一个目录则取其内容
    subs = [p for p in new_dir.iterdir()] if new_dir.exists() else []
    if len(subs) == 1 and subs[0].is_dir():
        inner = subs[0]
        if not any(p.is_file() and p.name.endswith(".exe") for p in new_dir.iterdir()):
            new_dir = inner

    if on_progress:
        on_progress("启动更新脚本...")
    install = install_dir()
    ps1 = _write_updater_script(info, new_dir, install)
    try:
        subprocess.Popen(
            ["powershell", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
             "-File", str(ps1)],
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
            close_fds=True,
            cwd=str(install),
        )
    except FileNotFoundError as e:
        raise RuntimeError("无法启动更新脚本 (找不到 powershell)") from e