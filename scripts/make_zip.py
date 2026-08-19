#!/usr/bin/env python3
"""build_release.ps1 的 zip 打包辅助脚本。

用 Python 标准库 topicfile 确定性打包，替代 tar，规避不同系统 tar 对裸路径
录制方式不一致导致 zip 出现 './' 前缀条目（解压后显示为 '.' 假文件夹）的问题。

用法: python make_zip.py <src_dir> <out_zip>
  src_dir : 待打包目录（如 dist/SanguiHelper）
  out_zip : 输出 zip 路径（如 dist/SanguiHelper-v1.0.3.zip）

产物：以 src_dir 为 zip 根，条目不含 './' 前缀，首层直接是 src_dir 下的子项。
"""
import os
import sys
import zipfile
from pathlib import PurePosixPath


def make_zip(src_dir: str, out_zip: str) -> None:
    src = os.path.abspath(src_dir)
    if not os.path.isdir(src):
        raise SystemExit(f"源目录不存在: {src}")

    out = os.path.abspath(out_zip)
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    src_posix = src.replace("\\", "/")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(src):
            root_posix = root.replace("\\", "/")
            rel_root = PurePosixPath(root_posix).relative_to(PurePosixPath(src_posix))
            # 目录条目（不含 './'、不含空 name；根目录本身不入 zip）
            for d in sorted(dirs):
                arc = str(rel_root / d) + "/"
                zf.writestr(arc, b"")
            for f in sorted(files):
                full = os.path.join(root, f)
                arc = str(rel_root / f)
                zf.write(full, arc)

    total = len(zipfile.ZipFile(out).namelist())
    print(f"已打包 {total} 个条目 -> {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("用法: python make_zip.py <src_dir> <out_zip>")
    make_zip(sys.argv[1], sys.argv[2])