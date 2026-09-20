"""运行环境自检：Python、GPU、外部工具、依赖、前端 vendor、第三方补丁状态。

纯探测函数，无路由。对外接口见 api.py。
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

NVIDIA_SMI_CANDIDATES = [
    r"C:\Windows\System32\nvidia-smi.exe",
    r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
]

# 网页预览三件套。每个文件给多个源，逐个回退。
VENDOR_SOURCES = {
    "live2dcubismcore.min.js": [
        "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js",
        "https://cdn.jsdelivr.net/gh/JourneyAd/pixi-live2d-display-extra@master/live2dcubismcore.min.js",
    ],
    "pixi.min.js": [
        "https://cdn.jsdelivr.net/npm/pixi.js@6.5.10/dist/browser/pixi.min.js",
        "https://unpkg.com/pixi.js@6.5.10/dist/browser/pixi.min.js",
    ],
    "pixi-live2d-display.min.js": [
        # 项目只产 Cubism4 模型，用 cubism4 构建；index 构建在初始化时
        # 强制要求 Cubism2 运行时（live2d.min.js），缺了会整个模块导出失败
        "https://cdn.jsdelivr.net/npm/pixi-live2d-display@0.4.0/dist/cubism4.min.js",
        "https://unpkg.com/pixi-live2d-display@0.4.0/dist/cubism4.min.js",
    ],
}


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _run(cmd: List[str], timeout: float = 8) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return (out.stdout or b"").decode("utf-8", "replace").strip()
    except Exception:
        return ""


def find_nvidia_smi() -> Optional[str]:
    """nvidia-smi 常常不在 PATH 里（服务进程从非终端环境启动时尤其如此）。"""
    p = shutil.which("nvidia-smi")
    if p:
        return p
    for c in NVIDIA_SMI_CANDIDATES:
        if Path(c).exists():
            return c
    return None


def gpu_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {"available": False, "name": "", "vram_gb": None}
    smi = find_nvidia_smi()
    if smi:
        out = _run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        parts = [p.strip() for p in out.split(",")] if out else []
        if len(parts) >= 2:
            try:
                info.update(available=True, name=parts[0],
                            vram_gb=round(float(parts[1]) / 1024, 1))
                return info
            except ValueError:
                pass
    try:
        import torch

        if torch.cuda.is_available():
            total = torch.cuda.get_device_properties(0).total_memory
            info.update(available=True, name=torch.cuda.get_device_name(0),
                        vram_gb=round(total / (1024 ** 3), 1))
    except Exception:
        pass
    return info


def check_see_through() -> Dict[str, Any]:
    raw = (config.resolve_tool("see_through_path") or "").strip()
    res: Dict[str, Any] = {"configured": bool(raw), "path": raw, "ok": False,
                           "scripts": [], "marigold_batch_patch": None, "note": ""}
    if not raw:
        res["note"] = "未配置路径；可在 tools/ 下放 see-through 仓库"
        return res
    root = Path(raw)
    if not root.exists():
        res["note"] = "路径不存在"
        return res
    scripts = root / "inference" / "scripts"
    found = sorted(p.name for p in scripts.glob("inference_psd*.py")) if scripts.exists() else []
    res["scripts"] = found
    res["ok"] = "inference_psd.py" in found
    if not res["ok"]:
        res["note"] = "未找到 inference/scripts/inference_psd.py，确认仓库完整"
        return res
    # 8GB 显存跑 Marigold 必须有「分批推理」补丁（L2D_DEPTH_BATCH），
    # 缺了会在深度阶段申请 31GB 显存直接 OOM
    quant = scripts / "inference_psd_quantized.py"
    if quant.exists():
        res["marigold_batch_patch"] = "L2D_DEPTH_BATCH" in quant.read_text(
            encoding="utf-8", errors="replace")
    return res


def check_image2live2d() -> Dict[str, Any]:
    raw = (config.resolve_tool("image2live2d_path") or "").strip()
    res: Dict[str, Any] = {"configured": bool(raw), "path": raw, "ok": False, "note": ""}
    if not raw:
        res["note"] = "未配置路径；可在 tools/ 下放 image2live2d 仓库"
        return res
    root = Path(raw)
    if not root.exists():
        res["note"] = "路径不存在"
        return res
    has_pkg = (root / "src" / "image2live2d").exists() or (root / "image2live2d").exists()
    res["ok"] = bool(has_pkg and (root / "pyproject.toml").exists())
    if not res["ok"]:
        res["note"] = "未找到 src/image2live2d 或 pyproject.toml"
    return res


def check_vendor() -> Dict[str, Any]:
    need = {
        "live2dcubismcore.min.js": "Cubism Core（必须，网页驱动模型用）",
        "pixi.min.js": "PixiJS（模型渲染）",
        "pixi-live2d-display.min.js": "pixi-live2d-display（模型加载）",
    }
    v = config.VENDOR_DIR
    items = []
    ready = True
    for name, desc in need.items():
        p = v / name
        ok = p.exists() and p.stat().st_size > 1024
        ready = ready and ok
        items.append({"name": name, "desc": desc, "ok": ok,
                      "size": p.stat().st_size if p.exists() else 0})
    return {"ok": ready, "dir": str(v), "items": items}


def suggest_precision(vram: Optional[float]) -> Dict[str, Any]:
    if vram is None:
        return {"precision": "bf16", "resolution": 1024, "group_offload": True,
                "note": "未探测到 NVIDIA GPU，若失败请降分辨率或改量化"}
    if vram >= 15:
        return {"precision": "bf16", "resolution": 1280, "group_offload": False,
                "note": f"{vram}GB 显存充足，走默认 bf16"}
    if vram >= 11:
        return {"precision": "bf16", "resolution": 1024, "group_offload": True,
                "note": f"{vram}GB 显存需开 group_offload"}
    # NF4 与 group_offload 互斥（会报 CUBLAS_STATUS_NOT_INITIALIZED），
    # 所以这一档 group_offload 报 False，与 README 的「强制关」一致
    return {"precision": "nf4", "resolution": 1024, "group_offload": False,
            "note": f"{vram}GB 显存偏低，建议 NF4 量化（需 bitsandbytes，自动关 group_offload）"}


def full_report() -> Dict[str, Any]:
    gpu = gpu_info()
    return {
        "python": {"version": sys.version.split()[0],
                   "exec": sys.executable,
                   "configured_exec": config.python_exe()},
        "gpu": gpu,
        "deps": {k: _has_module(k) for k in
                 ("rembg", "psd_tools", "PIL", "torch", "httpx")},
        "tools": {"see_through": check_see_through(),
                  "image2live2d": check_image2live2d()},
        "vendor": check_vendor(),
        "suggest_decomp_precision": suggest_precision(gpu.get("vram_gb")),
    }
