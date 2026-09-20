# -*- coding: utf-8 -*-
"""下载外部工具仓库并套上本地补丁（GitHub 上传版；仓库本体不进 git）。

新机器上没有 git 也能跑：按 pinned 提交号直接下 GitHub 的 zip 包，
解压后用 patches/<仓库名>/overlay/ 里的整文件快照覆盖，最后校验补丁标记。
顺手把网页预览依赖（server/web/vendor/）下齐 —— 与「环境自检」按钮同源。

用法：
    python tools\\fetch_tools.py
或双击项目根目录的「下载外部工具.bat」。幂等，可反复运行。
"""

from __future__ import annotations

import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
VENDOR = ROOT / "server" / "web" / "vendor"

# (owner/repo, 目录名, pinned 提交号, 补丁覆盖层, 校验标记: 文件 -> 必含字符串)
# pinned 提交号来自 patches/<目录名>/HEAD.txt；升级上游仓库后要重新导出补丁
REPOS = [
    ("shitagaki-lab/see-through", "see-through",
     "7f139bb25c46a0c8ac720d95ddab185fcda5451c",
     "see-through",
     {"inference/scripts/inference_psd_quantized.py": "L2D_DEPTH_BATCH"}),
    ("Wzhang3912/image2live2d", "image2live2d",
     "714e7cc9191f1ef6c9a1732c80e8b566ec127d6b",
     "image2live2d",
     {"src/image2live2d/__main__.py": "native_moc_writer"}),
]

# 与 server/envcheck.py 的 VENDOR_SOURCES 保持一致（主源 + 备源）
VENDOR_FILES = {
    "live2dcubismcore.min.js": [
        "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js",
        "https://cdn.jsdelivr.net/gh/JourneyAd/pixi-live2d-display-extra@master/live2dcubismcore.min.js",
    ],
    "pixi.min.js": [
        "https://cdn.jsdelivr.net/npm/pixi.js@6.5.10/dist/browser/pixi.min.js",
        "https://unpkg.com/pixi.js@6.5.10/dist/browser/pixi.min.js",
    ],
    "pixi-live2d-display.min.js": [
        "https://cdn.jsdelivr.net/npm/pixi-live2d-display@0.4.0/dist/cubism4.min.js",
    ],
}
MIN_VENDOR_BYTES = 1024  # 太小说明下到的是错误页


def fetch(url: str, timeout: int = 300) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "l2d-fetch-tools/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def download_repo(owner_repo: str, name: str, sha: str) -> None:
    dst = TOOLS / name
    if dst.exists():
        print(f"--> {name}: already present, skip download ({dst})")
        return
    zip_url = f"https://codeload.github.com/{owner_repo}/zip/{sha}"
    print(f"--> {name}: downloading {owner_repo}@{sha[:8]}")
    print(f"    {zip_url}")
    blob = fetch(zip_url)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
        top = names[0].split("/")[0]          # <repo>-<sha>/
        zf.extractall(TOOLS)
    extracted = TOOLS / top
    extracted.rename(dst)
    print(f"    OK  ({len(blob) // 1024 // 1024} MB) -> {dst}")


def apply_overlay(name: str) -> None:
    overlay = ROOT / "patches" / name / "overlay"
    if not overlay.is_dir():
        print(f"    [WARN] no overlay for {name}, skip")
        return
    dst = TOOLS / name
    n = 0
    for f in sorted(overlay.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(overlay)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        n += 1
    print(f"    overlay: {n} file(s) copied onto {dst}")


def verify_patch(name: str, markers: dict) -> bool:
    ok = True
    for rel, needle in markers.items():
        p = TOOLS / name / rel
        if not p.is_file():
            print(f"    [FAIL] missing {rel}")
            ok = False
            continue
        if needle not in p.read_text(encoding="utf-8", errors="replace"):
            print(f"    [FAIL] {rel} lost patch marker '{needle}'")
            ok = False
    return ok


def fetch_vendor() -> None:
    VENDOR.mkdir(parents=True, exist_ok=True)
    for fname, urls in VENDOR_FILES.items():
        dst = VENDOR / fname
        if dst.is_file() and dst.stat().st_size >= MIN_VENDOR_BYTES:
            print(f"--> vendor/{fname}: already present, skip")
            continue
        err = ""
        for url in urls:
            try:
                blob = fetch(url)
                if len(blob) < MIN_VENDOR_BYTES:
                    raise ValueError(f"too small ({len(blob)} B), likely an error page")
                dst.write_bytes(blob)
                print(f"--> vendor/{fname}: OK ({len(blob) // 1024} KB)")
                break
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
        else:
            print(f"--> vendor/{fname}: FAILED ({err})")


def main() -> int:
    print("=" * 62)
    print("  External tools fetcher (repos + local patches + web vendor)")
    print("=" * 62)
    print()

    failed = []
    for owner_repo, name, sha, _, markers in REPOS:
        print(f"==> {name} ({owner_repo})")
        try:
            download_repo(owner_repo, name, sha)
            apply_overlay(name)
            if not verify_patch(name, markers):
                failed.append(name)
            else:
                print("    patch check: OK")
        except Exception as exc:  # noqa: BLE001
            print(f"    FAILED: {type(exc).__name__}: {exc}")
            failed.append(name)
        print()

    print("==> web vendor (preview JS libs)")
    fetch_vendor()
    print()

    print("=" * 62)
    if failed:
        print(f"  {len(failed)} repo(s) failed: {', '.join(failed)}")
        print("  Fix the problems above, then re-run this script.")
        print("=" * 62)
        return 1
    print("  All set. Next steps on a fresh machine:")
    print("    1. 安装环境.bat            (python deps, several GB)")
    print("    2. 下载分层模型.bat        (~12 GB, only stage 3 needs it)")
    print("    3. 启动.bat                (open http://127.0.0.1:7800)")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
