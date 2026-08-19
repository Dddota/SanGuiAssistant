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

    分片源（Gitee 分卷上传）：若存在 `SanguiHelper-*.zip.NNN` 分片附件，
    收集所有分片并按序号升序排列为 parts 列表（此时无 download_url 单键）。
    单包源（GitHub）：照旧返回含 download_url 的 dict。
    """
    tag = data.get("tag_name", "")
    if not tag:
        raise RuntimeError("Release 缺少 tag_name")
    assets = data.get("assets") or data.get("attach_files") or []

    # 分片正则：SanguiHelper-*.zip 后跟 .NNN（三位数字）
    part_pat = re.compile(r"SanguiHelper-.*\.zip\.\d{3}$")
    parts = [
        (a, a.get("name", "")) for a in assets
        if part_pat.search(a.get("name", ""))
    ]
    if parts:
        # 按序号升序排序（.001 < .010 < .100 字典序即序号序）
        parts.sort(key=lambda x: x[1])
        return {
            "tag": tag,
            "name": parts[0][1],
            "parts": [
                a.get("browser_download_url", "") for a, _ in parts
            ],
            "body": data.get("body", ""),
        }

    # 单包模式：只认 SanguiHelper-*.zip，避免把 Gitee 源码包当更新包
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


def _url_size(url: str) -> int:
    """探测 url 的资源大小（字节）。无法得知返回 -1（不读 body）。

    优先用 HEAD 请求取 Content-Length；HEAD 不支持时回退到 GET 探测，
    拿到头部后立即关闭连接，不读取 body，避免整包下载。
    """
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": _UA}, method=method
            )
            with urllib.request.urlopen(req, timeout=_LATEST_TIMEOUT) as resp:
                cl = resp.headers.get("Content-Length")
                if cl is not None:
                    try:
                        return int(cl)
                    except ValueError:
                        return -1
        except Exception as e:  # noqa: BLE001
            logger.warning("_url_size(%s, %s) failed: %s", method, url, e)
    return -1


def _download(url: str, dest: Path, on_byte_progress=None) -> int:
    """流式下载 url 到 dest，避免大面积内存占用。

    on_byte_progress: Optional[Callable[[int, int], None]]，每次下载分块回调
    (downloaded 累计字节数, total 总字节数)，total 未知时为 -1。
    返回本次下载资源的总字节数（未知为 -1）。
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        cl = resp.headers.get("Content-Length")
        try:
            total = int(cl) if cl is not None else -1
        except ValueError:
            total = -1
        downloaded = 0
        while True:
            chunk = resp.read(DOWNLOAD_CHUNK)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            if on_byte_progress:
                on_byte_progress(downloaded, total)
    return total


def _join_parts(parts: list[Path], zip_path: Path) -> None:
    """把有序分片字节流式追加拼接为完整 zip（不整包读入内存）。

    parts 需已按序号升序排列。stream copy 逐片写入，适合大文件。
    """
    with open(zip_path, "wb") as out:
        for part in parts:
            with open(part, "rb") as src:
                shutil.copyfileobj(src, out, length=DOWNLOAD_CHUNK)


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

    脚本职责：等主进程退出 → 备份当前安装目录 → robocopy 覆盖 → 重启新 exe；
    若覆盖失败则从备份还原（保证旧版本仍可用）并清临时目录。
    """
    pid = os.getpid()
    main_exe = (install / "SanguiHelper.exe").resolve()
    pause = _script_pause_ms()
    backup = Path(tempfile.gettempdir()) / "sangui_backup"
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$mainExe = '{main_exe}'",
        f"$install = '{install}'",
        f"$newDir = '{new_dir}'",
        f"$backup = '{backup}'",
        f"$pid0 = {pid}",
        "function Start-App {",
        "    if (Test-Path $mainExe) { Start-Process -FilePath $mainExe -WorkingDirectory $install }",
        "}",
        "Start-Sleep -Milliseconds $pause",
        # 等待主进程（含已退出的竞态）结束
        "for ($i = 0; $i -lt 60; $i++) {",
        "    if (-not (Get-Process -Id $pid0 -ErrorAction SilentlyContinue)) { break }",
        "    Start-Sleep -Milliseconds 500",
        "}",
        # 备份当前安装目录（可回滚的保险）
        "if (Test-Path $backup) { Remove-Item $backup -Recurse -Force -ErrorAction SilentlyContinue }",
        "if (Test-Path $install) { Copy-Item $install $backup -Recurse -Force -ErrorAction Stop }",
        # 覆盖安装：/E 递归空目录 /IS /IT 含相同与更旧文件 /PURGE 删除目标多余文件
        "& robocopy $newDir $install /E /IS /IT /PURGE /NFL /NDL /NJH /NJS /NP | Out-Null",
        "if ($LASTEXITCODE -ge 8) {",
        "    Write-Output \"install-overwrite-failed code:$LASTEXITCODE; restore backup\"",
        # 覆盖失败：从备份还原旧版本，保证用户仍可用
        "    if (Test-Path $backup) {",
        "        & robocopy $backup $install /E /IS /IT /PURGE /NFL /NDL /NJH /NJS /NP | Out-Null",
        "    }",
        "    Start-App",
        "    exit 1",
        "}",
        # 清理临时目录与备份
        "if (Test-Path $newDir) { Remove-Item $newDir -Recurse -Force -ErrorAction SilentlyContinue }",
        "if (Test-Path $backup) { Remove-Item $backup -Recurse -Force -ErrorAction SilentlyContinue }",
        # 重启新版本
        "Start-App",
    ]
    ps1 = Path(tempfile.gettempdir()) / "sangui_updater.ps1"
    ps1.write_text("\r\n".join(lines), encoding="utf-8")
    return ps1


def apply_update(info: dict, on_progress=None, on_byte_progress=None) -> None:
    """下载并应用更新：下载 → 解压 → 启动独立更新脚本。

    on_progress: Optional[Callable[[str], None]]，用于阶段文本提示。
    on_byte_progress: Optional[Callable[[int, int], None]]，字节级进度回调
        (downloaded 累计已下载字节数, total 总字节数)，total 未知为 -1。
    本函数返回即表示"更新脚本已启动"，主程序应随后提示用户并自行退出。
    """
    workdir = Path(tempfile.gettempdir()) / "sangui_update"
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)

    # 按下表计算总大小：分片模式为各分片之和；任一未知则整体 -1
    parts = info.get("parts")
    if parts:
        sizes = [_url_size(u) for u in parts]
        total = sum(sizes) if all(s >= 0 for s in sizes) else -1
    else:
        total = _url_size(info["download_url"])

    if on_progress:
        on_progress("下载更新包...")
    zip_path = workdir / "package.zip"

    # ---- 下载阶段：任何失败统一归类为"下载失败" ----
    try:
        if parts:
            # 分片模式：下载每个分片到 parts/，再按序拼接为完整 zip
            parts_dir = workdir / "parts"
            parts_dir.mkdir(parents=True, exist_ok=True)
            downloaded_total = 0
            try:
                downloaded: list[Path] = []
                for i, url in enumerate(parts, 1):
                    part_path = parts_dir / f"{i:03d}"
                    if on_progress:
                        on_progress(f"下载更新包(分片 {i}/{len(parts)})...")
                    part_total = _download(
                        url, part_path,
                        on_byte_progress=(
                            (lambda d, t, off=downloaded_total:
                                (on_byte_progress and on_byte_progress(off + d, total)))
                            if on_byte_progress else None
                        ),
                    )
                    if on_byte_progress:
                        on_byte_progress(downloaded_total + part_total, total)
                    downloaded_total += part_total
                    downloaded.append(part_path)
                if on_progress:
                    on_progress("拼接分片...")
                _join_parts(downloaded, zip_path)
            finally:
                shutil.rmtree(parts_dir, ignore_errors=True)
        else:
            _download(
                info["download_url"], zip_path,
                on_byte_progress=(
                    (lambda d, t: (on_byte_progress and on_byte_progress(d, t)))
                    if on_byte_progress else None
                ),
            )
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"下载失败: {e}") from e

    # ---- 安装阶段：解压 / 写脚本 / 启动更新脚本，失败归类为"安装失败" ----
    try:
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
    except RuntimeError:
        raise
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"安装失败: {e}") from e