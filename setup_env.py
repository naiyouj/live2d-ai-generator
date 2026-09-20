# -*- coding: utf-8 -*-
"""One-click environment setup for Live2D AI Generator.

Run it with the Python you intend to use for generation:

    python setup_env.py

What it does
  1. Detects GPU / driver and picks the right CUDA build of PyTorch
  2. Installs see-through inference deps (trimmed: no Qt, no training extras)
  3. Installs image2live2d (editable) and rembg (optional)
  4. Installs the web console deps
  5. Writes data/config.json with tool paths + python executable

Output is deliberately ASCII-only so it survives any Windows codepage.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / "tools"
DATA = ROOT / "data"
CFG = DATA / "config.json"

MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
PYTORCH = "https://download.pytorch.org/whl/"

FAILS: list[tuple[str, list[str]]] = []
WARNS: list[str] = []


def sh(args, desc, index_url=None, optional=False, quiet=True):
    cmd = [sys.executable, "-m", "pip", "install", *args]
    if index_url:
        cmd += ["--index-url", index_url]
    else:
        cmd += ["-i", MIRROR]
    print(f"\n>>> {desc}")
    print(f"    $ {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="replace", timeout=5400)
    except subprocess.TimeoutExpired:
        print(f"[FAIL] {desc} :: timeout")
        FAILS.append((desc, args))
        return False
    if r.returncode == 0:
        print(f"[ OK ] {desc}")
        return True

    tail = (r.stdout or "")[-600:]
    print(f"[FAIL] {desc} (code {r.returncode})")
    if tail.strip():
        print("       " + tail.strip().replace("\n", "\n       ")[-600:])

    pkgs = [a for a in args if not a.startswith("-")]
    if len(pkgs) > 1:
        print("       retrying one by one...")
        missing = []
        for p in pkgs:
            if sh([p], f"{desc} :: {p}", index_url, optional=True):
                continue
            missing.append(p)
        if missing:
            (WARNS if optional else FAILS).append((desc, missing))
            print(f"[{'WARN' if optional else 'FAIL'}] {desc} missing: {missing}")
        return optional or not missing

    (WARNS if optional else FAILS).append((desc, pkgs))
    return optional


def gpu_probe():
    """Return (name, driver_major, vram_gb) or (None, None, None)."""
    smi = None
    for c in ("nvidia-smi", r"C:\Windows\System32\nvidia-smi.exe",
              r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
        p = __import__("shutil").which(c)
        if p:
            smi = p
            break
        if os.path.exists(c):
            smi = c
            break
    if not smi:
        return None, None, None
    try:
        out = subprocess.run(
            [smi, "--query-gpu=name,driver_version,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, errors="replace", timeout=30)
        line = (out.stdout or "").strip().splitlines()[0]
        parts = [x.strip() for x in line.split(",")]
        name = parts[0]
        drv = int(float(parts[1])) if len(parts) > 1 else None
        vram = round(float(parts[2]) / 1024, 1) if len(parts) > 2 else None
        return name, drv, vram
    except Exception as e:
        WARNS.append(f"nvidia-smi parse failed: {e}")
        return None, None, None


def pick_cuda_tag(driver):
    """CUDA wheel tag that the installed driver can actually run."""
    if driver is None:
        return "cu126"
    if driver >= 570:
        return "cu128"
    if driver >= 560:
        return "cu126"
    if driver >= 525:
        return "cu121"
    return "cpu"


TORCH_BY_TAG = {
    "cu128": ["torch==2.8.0+cu128", "torchvision==0.23.0+cu128"],
    "cu126": ["torch==2.8.0+cu126", "torchvision==0.23.0+cu126"],
    "cu121": ["torch==2.5.1+cu121", "torchvision==0.20.1+cu121"],
    "cpu": ["torch==2.8.0", "torchvision==0.23.0"],
}


def main():
    print("=" * 62)
    print("  Live2D AI Generator - environment setup")
    print("=" * 62)
    print(f"  Python : {sys.version.split()[0]}")
    print(f"  Exec   : {sys.executable}")
    print(f"  Root   : {ROOT}")

    if sys.version_info < (3, 10):
        print("\n[FATAL] Python 3.10+ required.")
        return 2

    name, drv, vram = gpu_probe()
    if name:
        print(f"  GPU    : {name}  driver={drv}  VRAM={vram}GB")
    else:
        print("  GPU    : not detected (nvidia-smi unavailable)")
        WARNS.append("GPU not detected; will install CPU PyTorch")

    tag = pick_cuda_tag(drv)
    print(f"  CUDA   : {tag}" + (f"  (driver {drv})" if drv else ""))

    # ---------- 1. PyTorch ----------
    if tag == "cpu":
        sh(TORCH_BY_TAG["cpu"], "PyTorch (CPU)")
    else:
        if not sh(TORCH_BY_TAG[tag], f"PyTorch {tag}",
                  index_url=PYTORCH + tag, optional=True):
            print("       falling back to CPU build")
            sh(TORCH_BY_TAG["cpu"], "PyTorch (CPU fallback)")

    # ---------- 2. see-through inference deps ----------
    core = ["numpy", "pillow", "tqdm", "einops", "requests", "packaging",
            "psd-tools", "matplotlib", "safetensors", "accelerate",
            "huggingface-hub", "transformers", "diffusers",
            "opencv-python", "scipy"]
    sh(core, "see-through inference core")

    sh(["scikit-image", "omegaconf", "pyyaml", "kornia"],
       "see-through extras", optional=True)

    # bitsandbytes: required by NF4 path (<=8GB VRAM)
    if vram is not None and vram <= 11:
        sh(["bitsandbytes"], "bitsandbytes (NF4 quantization)",
           optional=True)

    # ---------- 3. see-through local packages ----------
    for sub in ("common", "annotators"):
        p = TOOLS / "see-through" / sub
        if (p / "pyproject.toml").exists():
            sh(["-e", str(p)], f"see-through::{sub}", optional=True)

    # ---------- 4. image2live2d ----------
    i2l = TOOLS / "image2live2d"
    if i2l.exists():
        sh(["-e", str(i2l)], "image2live2d")
        sh(["triangle", "numpy", "psd-tools"], "image2live2d extras",
           optional=True)
    else:
        WARNS.append(f"image2live2d not found at {i2l}")

    # ---------- 5. rembg (optional) ----------
    sh(["rembg"], "rembg (background removal)", optional=True)

    # ---------- 6. web console deps ----------
    sh(["fastapi", "uvicorn[standard]", "httpx", "python-multipart"],
       "web console deps")

    # ---------- 7. write config ----------
    DATA.mkdir(parents=True, exist_ok=True)
    cfg = {}
    if CFG.exists():
        try:
            cfg = json.loads(CFG.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}

    st = TOOLS / "see-through"
    cfg["see_through_path"] = str(st) if st.exists() else cfg.get("see_through_path", "")
    cfg["image2live2d_path"] = str(i2l) if i2l.exists() else cfg.get("image2live2d_path", "")
    cfg["python_exec"] = sys.executable

    if vram is not None:
        if vram >= 15:
            cfg["decomp_precision"], cfg["decomp_resolution"] = "bf16", 1280
            cfg["decomp_group_offload"] = False
        elif vram >= 11:
            cfg["decomp_precision"], cfg["decomp_resolution"] = "bf16", 1024
            cfg["decomp_group_offload"] = True
        else:
            cfg["decomp_precision"], cfg["decomp_resolution"] = "nf4", 1024
            cfg["decomp_group_offload"] = True

    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[ OK ] config written -> {CFG}")
    for k in ("see_through_path", "image2live2d_path", "python_exec",
              "decomp_precision", "decomp_resolution", "decomp_group_offload"):
        print(f"       {k:22s} = {cfg.get(k)}")

    # ---------- 8. verify ----------
    print("\n" + "=" * 62)
    print("  Verification")
    print("=" * 62)
    code = (
        "import torch,sys;"
        "print('torch',torch.__version__);"
        "print('cuda',torch.cuda.is_available());"
        "print('gpu',torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, errors="replace")
    print((r.stdout or r.stderr or "").strip())

    print("\n" + "=" * 62)
    if FAILS:
        print(f"  FAILED ({len(FAILS)}):")
        for d, items in FAILS:
            print(f"    - {d}: {items}")
    if WARNS:
        print(f"  WARNINGS ({len(WARNS)}):")
        for w in WARNS:
            print(f"    - {w}")
    if not FAILS:
        print("  Setup complete. Run: python run.py   (or double-click 启动.bat)")
    else:
        print("  Setup finished with failures. Re-run this script to retry.")
    print("=" * 62)
    return 1 if FAILS else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[abort] interrupted")
        sys.exit(130)
