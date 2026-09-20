# -*- coding: utf-8 -*-
"""预下载 see-through 分层流程所需的全部模型。

分层步骤依赖三个 HuggingFace 仓库，首次运行会边跑边下，
中途容易被网络/中断打断。提前跑这个脚本可以一次性下齐。

用法：
    .venv\\Scripts\\python.exe tools\\download_models.py
或直接双击项目根目录的「下载分层模型.bat」。
"""

from __future__ import annotations

import sys
import time

try:
    from huggingface_hub import snapshot_download
except ImportError:
    print("[ERROR] huggingface_hub not installed. Run: pip install huggingface_hub")
    sys.exit(1)


# (repo_id, allow_patterns, 说明)
JOBS = [
    (
        "24yearsold/seethroughv0.0.2_layerdiff3d_nf4",
        None,
        "LayerDiff3D 分层主模型 (NF4 量化, 约 10 GB)",
    ),
    (
        "24yearsold/seethroughv0.0.1_marigold_nf4",
        None,
        "Marigold 深度估计模型 (NF4 量化, 约 1.8 GB)",
    ),
    (
        "frankjoshua/juggernautXL_version6Rundiffusion",
        ["scheduler/*", "model_index.json"],
        "SDXL scheduler 配置 (仅需几十 KB, 不要下整仓 26 GB)",
    ),
]


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def main() -> int:
    print("=" * 62)
    print("  See-through model pre-downloader")
    print("  Total about 12 GB on first run.")
    print("  Already-downloaded files are skipped automatically.")
    print("=" * 62)
    print()

    failed = []
    for repo, allow, desc in JOBS:
        print(f"--> {desc}")
        print(f"    {repo}")
        if allow:
            print(f"    partial: {allow}")
        t0 = time.time()
        try:
            path = snapshot_download(repo, allow_patterns=allow, max_workers=4)
            print(f"    OK  ({time.time() - t0:.0f}s)")
            print(f"    -> {path}")
        except Exception as exc:  # noqa: BLE001
            print(f"    FAILED: {type(exc).__name__}: {exc}")
            failed.append(repo)
        print()

    print("=" * 62)
    if failed:
        print(f"  {len(failed)} repo(s) failed:")
        for f in failed:
            print(f"    - {f}")
        print("  Re-run this script to retry (finished files are kept).")
        print("=" * 62)
        return 1

    print("  All models are ready. You can run stage 3 (layering) now.")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
