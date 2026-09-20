"""子进程输出 → 界面进度的换算器。

see-through 没有结构化进度回调，只能解析它打印的行。这里用两层信息：

- 脚本自己 print 的阶段标记（Building / Running / done）负责切相位；
- tqdm 进度条（形如 ` 25%|██▌  | 7/30 [00:38<18:44, 38.78s/it]`）
  负责在相位内部插值。

区间按一次实测跑通的耗时占比划分（1024 分辨率 / NF4 / RTX 2070 8GB）：

    建 LayerDiff 管道      3%  →  5%     （加载权重，约 1 分钟）
    LayerDiff body 30 步   8%  → 41%     （约 22 分钟）
    LayerDiff head 30 步  41%  → 74%     （约 19 分钟）
    建 Marigold 管道      76%  → 78%
    Marigold 8 段         79%  → 96%     （约 11 分钟）
    PSD 拼装              98%  → 99%

这套映射只决定进度条走得多快，不参与任何计算，改错了也不影响产物；
test_progress_mapping.py 用真实日志回放校验它的单调性。
"""

from __future__ import annotations

import re
from typing import Optional


def make_decompose_progress():
    st = {"phase": "boot", "ld_pass": 0, "mg_chunk": 0}
    LD_TOTAL = 2    # LayerDiff 分 body / head 两遍，各 30 步
    MG_TOTAL = 8    # Marigold 按 L2D_DEPTH_BATCH=3 分批，21 张图实测 8 段

    def on_line(line: str) -> Optional[int]:
        low = line.lower()
        if "building layerdiff" in low:
            st["phase"] = "ld_load"
            return 3
        if "running layerdiff" in low:
            st["phase"], st["ld_pass"] = "ld_run", 0
            return 8
        if "layerdiff3d done" in low:
            st["phase"] = "ld_done"
            return 74
        if "building marigold" in low:
            st["phase"] = "mg_load"
            return 76
        if "running marigold" in low:
            st["phase"], st["mg_chunk"] = "mg_run", 0
            return 79
        if "marigold done" in low:
            st["phase"] = "mg_done"
            return 97
        if "running psd assembly" in low:
            st["phase"] = "psd"
            return 98
        if "psd saved" in low or "stats saved" in low:
            return 99

        m = re.search(r"(\d+)\s*/\s*(\d+)", line)
        if not (m and "%|" in line):
            return None
        cur, tot = int(m.group(1)), int(m.group(2))
        frac = (cur / tot) if tot else 0.0
        phase = st["phase"]

        if phase == "ld_run":
            pct = 8 + int((st["ld_pass"] + frac) / LD_TOTAL * 66)
            if cur >= tot and tot >= 20:   # 一遍跑满 30 步，切到下一遍
                st["ld_pass"] = min(st["ld_pass"] + 1, LD_TOTAL)
            return min(pct, 74)
        if phase == "mg_run":
            pct = 79 + int(min(st["mg_chunk"] + frac, MG_TOTAL) / MG_TOTAL * 17)
            if cur >= tot:
                st["mg_chunk"] += 1
            return min(pct, 96)
        if phase == "ld_load":
            return 3 + int(frac * 3)
        if phase == "mg_load":
            return 76 + int(frac * 2)
        return None

    return on_line


# rig 阶段：image2live2d 打印的阶段关键词 → 百分比
_RIG_KEYWORDS = (("decompose", 20), ("mesh", 40), ("rig", 60),
                 ("physics", 75), ("motion", 85), ("emit", 92))


def make_rig_progress():
    def on_line(line: str) -> Optional[int]:
        low = line.lower()
        for kw, pct in _RIG_KEYWORDS:
            if kw in low:
                return pct
        return None

    return on_line
