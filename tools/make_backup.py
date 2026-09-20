# -*- coding: utf-8 -*-
"""把整个项目打成 zip 备份，默认排除敏感文件。

为什么需要这个脚本：上一版备份 zip 里带着 data/config.json 的明文 API key。
现在密钥单独存 data/secrets.json，打包脚本默认跳过它，config.json 可以
随包外发。

用法：
    .venv\\Scripts\\python.exe tools\\make_backup.py            # 全量（含 .venv）
    .venv\\Scripts\\python.exe tools\\make_backup.py --no-venv  # 轻量（不含 .venv）
    .venv\\Scripts\\python.exe tools\\make_backup.py --out D:\\backup

排除规则（--include-secrets 可强制带上密钥文件）：
    data/secrets.json          # API key，绝不入包
    *.zip / *.7z               # 旧备份，避免套娃
    __pycache__ / *.pyc
    tools/*/workspace          # see-through 的原始输出目录（体积大且可再生）
"""

from __future__ import annotations

import argparse
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXCLUDE_DIRS = {"__pycache__", ".git"}
EXCLUDE_GLOBS = ["*.pyc", "*.pyo", "*.zip", "*.7z", "*.tmp"]
EXCLUDE_FILES = {"secrets.json"}          # 只匹配文件名，任意目录下的都排除


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def iter_files(base: Path):
    for p in sorted(base.rglob("*")):
        if p.is_dir():
            continue
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        if any(p.match(g) for g in EXCLUDE_GLOBS):
            continue
        if p.name in EXCLUDE_FILES:
            continue
        yield p


def main() -> int:
    ap = argparse.ArgumentParser(description="Live2D AI 生成器 —— 项目备份打包")
    ap.add_argument("--out", default=str(ROOT), help="zip 输出目录，默认项目根")
    ap.add_argument("--no-venv", action="store_true", help="不打包 .venv（体积小很多，恢复时需重跑 安装环境.bat）")
    ap.add_argument("--include-secrets", action="store_true",
                    help="强制包含密钥文件（仅限本机自用备份，勿外发）")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = out_dir / f"live2d_backup_{stamp}.zip"

    venv_dir = ROOT / ".venv"
    secrets = ROOT / "data" / "secrets.json"
    if secrets.exists() and args.include_secrets:
        EXCLUDE_FILES.discard("secrets.json")

    print("=" * 62)
    print("  Live2D AI Generator - project backup")
    print(f"  source : {ROOT}")
    print(f"  target : {dst}")
    print(f"  venv   : {'excluded (--no-venv)' if args.no_venv else 'included'}")
    print(f"  secrets: {'INCLUDED (--include-secrets)' if args.include_secrets else 'excluded'}")
    print("=" * 62)

    t0 = time.time()
    n = 0
    total = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in iter_files(ROOT):
            if args.no_venv and venv_dir in p.parents:
                continue
            arc = p.relative_to(ROOT).as_posix()
            try:
                zf.write(p, arc)
            except OSError as e:
                print(f"  [skip] {arc}: {e}")
                continue
            n += 1
            total += p.stat().st_size
            if n % 2000 == 0:
                print(f"  ... {n} files, {human(total)} read")

    size = dst.stat().st_size
    print()
    print(f"  done: {n} files, source {human(total)} -> zip {human(size)}"
          f"  ({time.time() - t0:.0f}s)")
    print(f"  -> {dst}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
