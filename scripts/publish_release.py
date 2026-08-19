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


def _api(path: str, method: str, *, token: str, data=None, files=None) -> dict:
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
        with request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except request.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise SystemExit(
            f"Gitee API {method} {path} 失败 (HTTP {e.code}): {detail}") from e


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
    )
    release_id = created.get("id")
    if not release_id:
        raise SystemExit(f"创建 Release 成功但未拿到 id: {created}")

    print(f"==> 上传附件 {zip_path.name} (id={release_id})")
    blob = zip_path.read_bytes()
    ctype = mimetypes.guess_type(zip_path.name)[0] or "application/zip"
    uploaded = _api(
        f"/releases/{release_id}/attach_files", "POST", token=args.token,
        data={"access_token": args.token},
        files={"file": (zip_path.name, blob, ctype)},
    )
    url = uploaded.get("browser_download_url") or uploaded.get("download_url")
    print("发布完成:")
    print(f"  版本: {tag}")
    print(f"  附件: {zip_path.name} ({zip_path.stat().st_size} bytes)")
    print(f"  下载: {url}")
    if not url:
        print("  警告: 未拿到下载 URL，可能附件字段名不同，请到 Gitee 网页核对。")


if __name__ == "__main__":
    main()