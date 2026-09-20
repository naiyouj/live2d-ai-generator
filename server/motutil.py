"""动作文件的小工具：待机动作剔除 Z 轴（面内旋转）曲线。

image2live2d 自动生成的待机动作带 ParamAngleZ / ParamBodyAngleZ 的整圈摆动，
AI 生成的网格做面内旋转会整体扭曲，观感很怪；2D 待机只需要 X/Y 摆动。
预览打包（stages.stage_preview）与手动修正接口（api.fix_idle）共用这里。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

Z_PARAM_IDS = {"ParamAngleZ", "ParamBodyAngleZ"}


def strip_idle_z(model3: Path) -> int:
    """把 model3.json 的 Idle 组动作里的 Z 轴曲线删掉，返回删除的曲线数。

    幂等：已经删过的文件再跑一遍返回 0，不会误伤 Custom 等其它组的动作。
    """
    meta = json.loads(model3.read_text(encoding="utf-8"))
    idle = ((meta.get("FileReferences") or {}).get("Motions") or {}).get("Idle") or []
    changed = 0
    root = model3.parent.resolve()
    for m in idle:
        rel = m.get("File") if isinstance(m, dict) else None
        if not rel:
            continue
        f = (model3.parent / rel).resolve()
        try:
            f.relative_to(root)
        except ValueError:
            continue
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        curves: List[dict] = data.get("Curves") or []
        keep = [c for c in curves if c.get("Id") not in Z_PARAM_IDS]
        if len(keep) == len(curves):
            continue
        data["Curves"] = keep
        meta_obj = data.get("Meta")
        if isinstance(meta_obj, dict):
            meta_obj["CurveCount"] = len(keep)
        f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        changed += len(curves) - len(keep)
    return changed
