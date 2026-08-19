"""发布脚本：把构建好的发布 zip 上传到 Gitee Release（附带自动更新使用）。

用法（需先在 https://gitee.com/dashboard/personal_access_tokens 生成私人令牌，
勾选 projects 权限）：

    python scripts/publish_release.py --token <TOKEN> [--zip <path>] [--tag v1.0.0]

流程：
1. 从 app/__init__.py 读 __version__ 作为默认版本号（tag = v{__version__}）。
2. 找到构建产物 SanguiHelper-<ver>.zip（可用 --zip 指定）。
3. 调 Gitee API 创建 Release（POST /releases），再上传附件
   （POST /releases/{id}/attach_files, multipart file 字段）。
4. 打印附件 browser_download_url（即客户端自动更新读取的下载地址）。

仅用 Python 标准库（urllib），无第三方依赖。
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sys
import tempfile
import uuid
from pathlib import Path
from urllib import request

# Windows 控制台 / CI（GitHub Actions windows-latest 默认 cp1252 等）非 UTF-8，
# 强制标准流用 UTF-8，避免打印中文说明时 UnicodeEncodeError 崩溃。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass  # 过老的 Python 无 reconfigure，忽略

OWNER = "Dddota"
REPO = "SanGuiAssistant"
API = f"https://gitee.com/api/v5/repos/{OWNER}/{REPO}"


def load_version(root: Path) -> str:
    """从 app/__init__.py 读取 __version__。"""
    text = (root / "app" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        raise SystemExit("未在 app/__init__.py 中找到 __version__")
    return m.group(1)


def _api(path: str, method: str, *, token: str, data=None, files=None,
         timeout: int = 60) -> dict:
    """调 Gitee API。files: {field: (filename, bytes, mime)}。"""
    url = f"{API}{path}?access_token={token}"
    headers = {"User-Agent": "SanguiHelper-Publisher/1.0"}
    body = None
    if files:
        boundary = uuid.uuid4().hex
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        body = _multipart(data or {}, files, boundary)
    elif data:
        body = urllib_urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except request.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise SystemExit(
            f"Gitee API {method} {path} 失败 (HTTP {e.code}): {detail}") from e


def _find_release_by_tag(tag: str, *, token: str) -> dict | None:
    """按 tag 查已有 Release。Gitee 的 GET /releases/tags/{tag} 存在则返回，
    不存在（HTTP 404）返回 None。用于幂等：重跑时不重复创建。"""
    try:
        return _api(f"/releases/tags/{tag}", "GET", token=token)
    except SystemExit as e:
        msg = str(e)
        # 404 = 该 tag 还没有 Release，属正常，返回 None
        if "HTTP 404" in msg:
            return None
        raise


def _list_attachments(release_id: int, *, token: str) -> dict:
    """列出某 Release 已上传的附件，用于幂等判断是否已传过同名 zip。"""
    try:
        return _api(f"/releases/{release_id}/attach_files", "GET", token=token)
    except SystemExit as e:
        if "HTTP 404" in str(e):
            return {}
        raise


def _multipart(fields: dict, files: dict, boundary: str) -> bytes:
    """构造 multipart/form-data body：access_token 等文本字段 + file 二进制。"""
    lines: list[bytes] = []
    for name, value in fields.items():
        lines += [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="{name}"'.encode(),
            b"",
            str(value).encode("utf-8"),
        ]
    for name, (filename, blob, ctype) in files.items():
        lines += [
            f"--{boundary}".encode(),
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"'
            ).encode(),
            f"Content-Type: {ctype or 'application/octet-stream'}".encode(),
            b"",
            blob,
        ]
    lines.append(f"--{boundary}--".encode())
    return b"\r\n".join(lines) + b"\r\n"


def urllib_urlencode(data: dict) -> str:
    from urllib.parse import urlencode
    return urlencode(data)


PART_SIZE = 80 * 1024 * 1024  # 80MB，远小于 Gitee 单附件 100M 上限


def _split_parts(zip_path: Path, part_size: int = PART_SIZE) -> list[Path]:
    """按 part_size 字节把 zip 切成连续分片临时文件，返回分片路径列表。

    分片文件名基于 zip_path.name 加上三位零填充序号（从 001 开始），
    例如 SanguiHelper-v1.0.0.zip -> SanguiHelper-v1.0.0.zip.001 / .002 / ...
    所有分片按序号顺序字节拼接即可无损还原原 zip。
    """
    total = zip_path.stat().st_size
    parts_dir = Path(tempfile.mkdtemp(
        prefix=f"partition_{zip_path.name}_",
        dir=str(zip_path.parent),
    ))
    paths: list[Path] = []
    try:
        with zip_path.open("rb") as src:
            index = 1
            while True:
                blob = src.read(part_size)
                if not blob:
                    break
                name = f"{zip_path.name}.{index:03d}"
                part = parts_dir / name
                part.write_bytes(blob)
                paths.append(part)
                index += 1
        if not paths:
            raise SystemExit(f"zip 为空或不可读: {zip_path}")
        return paths
    except Exception:
        # 分裂失败时清理已生成的分片
        for p in paths:
            try:
                p.unlink()
            except OSError:
                pass
        try:
            parts_dir.rmdir()
        except OSError:
            pass
        raise


def find_zip(root: Path, version: str) -> Path:
    candidates = [
        root / "dist" / f"SanguiHelper-{version}.zip",
        root / "dist" / f"SanguiHelper-v{version}.zip",
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise SystemExit(
        f"未找到发布 zip（尝试过 {[str(c) for c in candidates]}），请先运行 build_release.ps1")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="上传发布 zip 到 Gitee Release")
    ap.add_argument("--token", required=True, help="Gitee 私人令牌（projects权限）")
    ap.add_argument("--zip", default=None, help="zip 路径（默认 dist/SanguiHelper-<ver>.zip）")
    ap.add_argument("--tag", default=None, help="版本标签，默认 v{__version__}")
    ap.add_argument("--body", default="", help="Release 发布说明")
    ap.add_argument("--prerelease", action="store_true", help="标记为预发布")
    args = ap.parse_args()

    version = args.tag.lstrip("v") if args.tag else load_version(root)
    tag = args.tag or f"v{version}"
    zip_path = Path(args.zip) if args.zip else find_zip(root, version)
    if not zip_path.is_file():
        raise SystemExit(f"zip 不存在: {zip_path}")

    # 幂等：Release 已存在则复用（如上次上传中途超时），否则新建
    existing = _find_release_by_tag(tag, token=args.token)
    if existing and existing.get("id"):
        release_id = existing["id"]
        print(f"==> Release {tag} 已存在 (id={release_id})，复用")
    else:
        print(f"==> 创建 Release {tag}")
        created = _api(
            "/releases", "POST", token=args.token,
            data={
                "tag_name": tag,
                "target_commitish": "master",
                "name": f"v{tag}",
                "body": args.body,
                "prerelease": "true" if args.prerelease else "false",
            },
            timeout=120,
        )
        release_id = created.get("id")
        if not release_id:
            raise SystemExit(f"创建 Release 成功但未拿到 id: {created}")

    # 分卷上传：把 zip 切成 <100M 的分片逐片上传，绕开 Gitee 单附件 100M 上限。
    attach_list = _list_attachments(release_id, token=args.token)
    existing_names = {
        a.get("name") for a in attach_list
    } if isinstance(attach_list, list) else set()

    parts = _split_parts(zip_path, PART_SIZE)
    try:
        urls: dict[str, str] = {}
        for part in parts:
            name = part.name
            # 幂等：该分片已上传过则跳过
            if name in existing_names:
                print(f"==> 分片 {name} 已在上次上传，跳过上传 (id={release_id})")
                url = next(
                    (a.get("browser_download_url") or a.get("download_url")
                     for a in attach_list if a.get("name") == name),
                    "",
                )
                urls[name] = url
                continue

            print(f"==> 上传分片 {name} ({part.stat().st_size} bytes, id={release_id})")
            blob = part.read_bytes()
            ctype = mimetypes.guess_type(zip_path.name)[0] or "application/zip"
            # 上传超时放大到 600s：Gitee API 从 CI 主机回传分片可能很慢
            uploaded = _api(
                f"/releases/{release_id}/attach_files", "POST", token=args.token,
                data={"access_token": args.token},
                files={"file": (name, blob, ctype)},
                timeout=600,
            )
            urls[name] = (
                uploaded.get("browser_download_url")
                or uploaded.get("download_url") or ""
            )

        print("发布完成:")
        print(f"  版本: {tag}")
        print(f"  附件: {zip_path.name} ({zip_path.stat().st_size} bytes) -> {len(parts)} 个分片")
        for i, part in enumerate(parts, 1):
            url = urls.get(part.name, "")
            print(f"  分片 {part.name}: {url}")
            if not url:
                print(f"  警告: 未拿到分片 {part.name} 下载 URL，请到 Gitee 网页核对。")
    finally:
        # 无论成功失败都清理临时目录下的分片
        parts_dir = parts[0].parent if parts else None
        for p in parts:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        if parts_dir is not None:
            try:
                parts_dir.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    main()