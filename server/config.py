"""全局配置：defaults <- data/config.json <- data/secrets.json，按 SCHEMA 类型化。

- config.json 只存非敏感项，可以随项目打包外发；
- api_key 等敏感项单独放 data/secrets.json，备份打包脚本默认排除它；
- 读取/写入都按 SCHEMA 归一类型（旧的 "7800"、"30" 这类字符串一律修正），
  不在 SCHEMA 里的旧键直接丢弃，避免历史遗留字段越积越多；
- 落盘时只写「与默认值不同」的键，DEFAULTS 改了旧机器也能跟着生效。

首次导入时自动迁移旧版 config.json（剥离密钥、剔除废弃键、恢复被测试
污染的提示词字段）。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
WORKSPACE_DIR = ROOT / "workspace"
TOOLS_DIR = ROOT / "tools"
WEB_DIR = Path(__file__).resolve().parent / "web"
VENDOR_DIR = WEB_DIR / "vendor"
LOG_DIR = ROOT / "logs"

CONFIG_FILE = DATA_DIR / "config.json"
SECRETS_FILE = DATA_DIR / "secrets.json"

for _d in (DATA_DIR, WORKSPACE_DIR, TOOLS_DIR, LOG_DIR, VENDOR_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DEFAULT_POSITIVE_SUFFIX = (
    "1girl, solo, full body, standing, front view, a-pose, "
    "arms slightly away from body, symmetrical, centered, "
    "simple background, white background, anime style, clean lineart, "
    "flat color, crisp lines, masterpiece, best quality, ultra-detailed, "
    "high resolution"
)

DEFAULT_NEGATIVE = (
    "multiple views, multiple girls, complex background, gradient background, "
    "arms crossed, hands on hips, dynamic pose, perspective, foreshortening, "
    "sketchy lines, blurry, realistic, photo, 3d render, watermark, text, logo"
)

# 白名单 + 归一依据：不在表里的键一律不进配置
SCHEMA: Dict[str, Any] = {
    # 服务
    "host": str,
    "port": int,
    # 生图
    "gen_mode": str,            # upload | api | comfyui
    "comfyui_url": str,
    "comfyui_workflow": str,
    "api_base": str,
    "api_model": str,
    "positive_suffix": str,
    "negative_prompt": str,
    # 去背景
    "rembg_model": str,
    # 分层
    "decomp_precision": str,    # auto | bf16 | nf4
    "decomp_resolution": int,
    "decomp_depth_resolution": int,
    "decomp_steps": int,
    "decomp_group_offload": bool,
    # 绑骨
    "rig_emit_live2d": bool,
    # 外部工具
    "see_through_path": str,
    "image2live2d_path": str,
    "python_exec": str,
}
SECRET_KEYS = frozenset({"api_key"})

DEFAULTS: Dict[str, Any] = {
    "host": "127.0.0.1",
    "port": 7800,
    "gen_mode": "upload",
    "comfyui_url": "http://127.0.0.1:8188",
    "comfyui_workflow": "",
    "api_base": "",
    "api_model": "",
    "positive_suffix": DEFAULT_POSITIVE_SUFFIX,
    "negative_prompt": DEFAULT_NEGATIVE,
    "rembg_model": "isnet-general-use",
    "decomp_precision": "auto",
    "decomp_resolution": 1024,
    "decomp_depth_resolution": 768,
    "decomp_steps": 30,
    "decomp_group_offload": False,
    "rig_emit_live2d": True,
    "see_through_path": "",
    "image2live2d_path": "",
    "python_exec": "",
    "api_key": "",
}

_lock = threading.RLock()


def _coerce(key: str, value: Any) -> Any:
    """把任意值归一成 SCHEMA 声明的类型，失败回落默认值。"""
    want = SCHEMA.get(key)
    if want is None:            # 密钥键不在 SCHEMA，按原样保留字符串
        return str(value)
    try:
        if want is bool:
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "on")
        if want is int:
            return int(float(str(value).strip()))
        return want(str(value))
    except (TypeError, ValueError):
        return DEFAULTS.get(key)


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _migrate_legacy() -> None:
    """旧版 data/config.json 的三个历史问题，一次性修掉：

    1. api_key 明文混在 config.json 里 → 挪进 secrets.json；
    2. 废弃键（api_image_param / decomp_use_comfyui / rembg_alpha_matting，
       新代码不读）→ 剔除；
    3. 提示词字段被测试值污染（negative_prompt="test neg"）→ 不迁移，
       回落到 DEFAULTS。
    """
    raw = _read_json(CONFIG_FILE)
    if not raw:
        return
    secrets = _read_json(SECRETS_FILE)

    changed = False
    if "api_key" in raw and raw["api_key"]:
        secrets["api_key"] = str(raw.pop("api_key"))
        changed = True

    clean: Dict[str, Any] = {}
    for k, v in raw.items():
        if k not in SCHEMA:
            changed = True
            continue
        if k in ("positive_suffix", "negative_prompt"):
            # 一律回落默认：正向后缀旧值与默认一致，负向已被测试值覆盖
            changed = True
            continue
        norm = _coerce(k, v)
        if norm != DEFAULTS.get(k):
            clean[k] = norm
        if norm != v:
            changed = True

    if changed or raw != clean:
        _write_json(CONFIG_FILE, clean)
    if secrets:
        _write_json(SECRETS_FILE, secrets)


_migrate_legacy()


def load() -> Dict[str, Any]:
    """返回合并后的完整配置（含密钥；对外输出前必须经 mask_secrets）。"""
    with _lock:
        cfg = dict(DEFAULTS)
        for k, v in _read_json(CONFIG_FILE).items():
            if k in SCHEMA:
                cfg[k] = _coerce(k, v)
        for k, v in _read_json(SECRETS_FILE).items():
            if k in SECRET_KEYS:
                cfg[k] = _coerce(k, v)
        return cfg


def save(patch: Dict[str, Any]) -> Dict[str, Any]:
    """局部更新并持久化。密钥键写 secrets.json，其余写 config.json。"""
    with _lock:
        secrets = _read_json(SECRETS_FILE)
        file_cfg = {k: v for k, v in _read_json(CONFIG_FILE).items() if k in SCHEMA}

        for k, v in patch.items():
            if k in SECRET_KEYS:
                if str(v).strip():
                    secrets[k] = _coerce(k, v)
                else:
                    secrets.pop(k, None)   # 清空即删除，否则界面上永远删不掉已存的 Key
            elif k in SCHEMA:
                norm = _coerce(k, v)
                if norm == DEFAULTS.get(k):
                    file_cfg.pop(k, None)     # 与默认一致就不落盘
                else:
                    file_cfg[k] = norm

        _write_json(CONFIG_FILE, file_cfg)
        _write_json(SECRETS_FILE, secrets)
        return load()


def mask_secrets(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """对外输出配置时抹掉密钥。"""
    out = dict(cfg)
    for k in SECRET_KEYS:
        if out.get(k):
            out[k] = "******"
    return out


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def resolve_tool(cfg_key: str) -> str:
    """取工具路径，为空或失效时在 tools/ 下自动探测。"""
    cfg = load()
    p = (cfg.get(cfg_key) or "").strip()
    if p and Path(p).exists():
        return p
    guesses = {
        "see_through_path": ["see-through", "See-through", "see_through"],
        "image2live2d_path": ["image2live2d", "Image2Live2D"],
    }.get(cfg_key, [])
    for g in guesses:
        cand = TOOLS_DIR / g
        if cand.exists():
            return str(cand)
    return p


def python_exe() -> str:
    """跑外部工具用的 Python 解释器。"""
    import sys

    p = (load().get("python_exec") or "").strip()
    if p and Path(p).exists():
        return p
    return sys.executable


def vram_gb() -> Optional[float]:
    """尽力探测总显存，失败返回 None。"""
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            total = torch.cuda.get_device_properties(0).total_memory
            return round(total / (1024 ** 3), 1)
    except Exception:
        pass
    return None
