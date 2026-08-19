"""Gitee Release 中继脚本：把 GitHub Release 的 zip 同步到 Gitee Release。

背景：GitHub Actions 的构建机在海外，直接往 Gitee 国内 CDN 上传大 zip 会被跨境
链路阻断（Write timed out）。而 Gitee Go 云端只有 Linux 容器，打不出 Windows exe。
因此采用"中继"方案：Windows 包仍由 GitHub Actions 打（产出 GitHub Release），
本脚本跑在一台能访问公网的国内服务器上，把最新 Release 的 zip 拉到本地再传 Gitee
（国内→国内，稳定）。幂等，可反复运行，也用于清理残缺的空 Release。

用法（Linux，纯标准库，无需 pip install）：

    # 首次：把 Gitee 私人令牌(projects 权限)传进去
    python3 scripts/gitee_relay.py --token <GITEE_TOKEN>

    # 配合 cron 定期同步（每小时跑一次）：
    #   */60 * * * *  cd /path/to/repo && python3 scripts/gitee_relay.py --token <GITEE_TOKEN> >> /var/log/gitee_relay.log 2>&1

依赖注解：GitHub 侧匿名读（无需 token）；Gitee 侧写入用 token。
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import tempfile
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from urllib import request
from urllib.error import HTTPError, URLError

GITHUB_OWNER = "Dddota"
GITHUB_REPO = "SanGuiAssistant"
GITEE_OWNER = "Dddota"
GITEE_REPO = "SanGuiAssistant"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
GITEE_API = f"https://gitee.com/api/v5/repos/{GITEE_OWNER}/{GITEE_REPO}"

UA = "SanguiHelper-Relay/1.0"


def _gh_latest_release() -> dict | None:
    """拉取 GitHub 最新正式 Release。无则返回 None。"""
    req = request.Request(f"{GITHUB_API}/releases/latest",
                          headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    try:
        with request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError:
        return None  # 404 = 还没有任何 Release
    assets = data.get("assets") or []
    zip_asset = next(
        (a for a in assets if a.get("name", "").endswith(".zip")), None)
    if not zip_asset:
        return None
    return {
        "tag": data.get("tag_name"),
        "name": zip_asset.get("name"),
        "url": zip_asset.get("browser_download_url"),
        "size": zip_asset.get("size"),
        "body": data.get("body") or "",
    }


def _gitee_request(method: str, path: str, *, token: str,
                   data=None, files=None, timeout: int = 300) -> dict | list | None:
    """调 Gitee API（带 token）。files: {field:(filename, bytes, mime)}。"""
    url = f"{GITEE_API}{path}?access_token={token}"
    headers = {"User-Agent": UA}
    body = None
    if files:
        boundary = uuid.uuid4().hex
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        body = _multipart(data or {}, files, boundary)
    elif data:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except HTTPError as e:
        if e.code == 404:
            return None
        detail = e.read().decode("utf-8", "ignore")
        raise RuntimeError(
            f"Gitee API {method} {path} 失败 (HTTP {e.code}): {detail}")


def _multipart(fields: dict, files: dict, boundary: str) -> bytes:
    lines: list[bytes] = []
    for name, value in fields.items():
        lines += [f"--{boundary}".encode(),
                  f'Content-Disposition: form-data; name="{name}"'.encode(),
                  b"", str(value).encode("utf-8")]
    for name, (filename, blob, ctype) in files.items():
        lines += [f"--{boundary}".encode(),
                  (f'Content-Disposition: form-data; name="{name}"; '
                   f'filename="{filename}"').encode(),
                  f"Content-Type: {ctype or 'application/octet-stream'}".encode(),
                  b"", blob]
    lines.append(f"--{boundary}--".encode())
    return b"\r\n".join(lines) + b"\r\n"


def _download(url: str, dest: Path) -> None:
    """流式下载到大文件，避免内存占用。"""
    req = request.Request(url, headers={"User-Agent": UA})
    with request.urlopen(req, timeout=600) as resp, open(dest, "wb") as f:
        total = 0
        while True:
            chunk = resp.read(1 << 20)  # 1 MiB
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)


def _version_tuple(v: str) -> tuple:
    """从 tag 提取数值版本，用于比较：'v1.0.0' -> (1,0,0)。"""
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:3])


def _attachment_name(release: dict) -> str | None:
    assets = release.get("assets") or release.get("attach_files") or []
    for a in assets:
        if a.get("name", "").endswith(".zip"):
            return a["name"]
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="GitHub Release -> Gitee Release 中继")
    ap.add_argument("--token", required=True, help="Gitee 私人令牌（projects 权限）")
    ap.add_argument("--min-tag", default=None,
                    help="仅同步 tag 数值 >= 该版本的 Release（默认全部同步最新）")
    args = ap.parse_args()

    gh = _gh_latest_release()
    if not gh:
        print("GitHub 无可用 Release，跳过。")
        return

    tag = gh["tag"]
    if args.min_tag and _version_tuple(tag) < _version_tuple(args.min_tag):
        print(f"GitHub 最新 {tag} 低于 --min-tag {args.min_tag}，跳过。")
        return

    # 列出 Gitee 已有 Release（token 读）
    gitee_list = _gitee_request("GET", "/releases", token=args.token)
    gitee_list = gitee_list if isinstance(gitee_list, list) else []
    same_tag = [r for r in gitee_list if r.get("tag_name") == tag]
    already = [r for r in same_tag if _attachment_name(r) == gh["name"]]
    if already:
        print(f"Gitee 已有 {tag} 的 {gh['name']}，无需同步。")
        return

    # 删除该 tag 下残缺/重复的 Release（不含目标附件），留干净再重建
    for r in same_tag:
        rid = r.get("id")
        cur = _attachment_name(r)
        print(f"清理残缺 Release {tag} id={rid} (附件={cur})")
        _gitee_request("DELETE", f"/releases/{rid}", token=args.token)

    print(f"下载 GitHub Release {tag} zip -> {gh['name']}")
    with tempfile.TemporaryDirectory(prefix="gitee_relay_") as tmp:
        zip_path = Path(tmp) / gh["name"]
        _download(gh["url"], zip_path)
        print(f"下载完成: {zip_path.stat().st_size} bytes")

        print(f"创建 Gitee Release {tag}")
        rel = _gitee_request(
            "POST", "/releases", token=args.token,
            data={
                "tag_name": tag,
                "target_commitish": "master",
                "name": f"v{tag}",
                "body": gh["body"],
                "prerelease": "false",
            }, timeout=120,
        )
        if not rel or not rel.get("id"):
            raise RuntimeError(f"创建 Gitee Release 失败: {rel}")
        release_id = rel["id"]

        ctype = mimetypes.guess_type(zip_path.name)[0] or "application/zip"
        blob = zip_path.read_bytes()
        print(f"上传附件 {zip_path.name} (id={release_id})")
        up = _gitee_request(
            f"/releases/{release_id}/attach_files", "POST", token=args.token,
            data={"access_token": args.token},
            files={"file": (zip_path.name, blob, ctype)},
            timeout=600,
        )
        url = (up or {}).get("browser_download_url") or (up or {}).get("download_url")
        print(f"同步完成: {tag} out of GitHub in Gitee")
        print(f"  下载: {url}")


if __name__ == "__main__":
    main()