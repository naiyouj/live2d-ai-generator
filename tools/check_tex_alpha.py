# -*- coding: utf-8 -*-
"""检查 Live2D 贴图/图层的 alpha 通道：找出带不透明背景的贴图（渲染会成色块）。"""
import sys
from pathlib import Path

from PIL import Image

TARGETS = [
    ("PREVIEW TEXTURES", Path(r"workspace/20260916-215808-f3b407/preview/textures")),
    ("RIG LAYERS", Path(r"workspace/20260916-215808-f3b407/rig/character_layers")),
    ("DECOMPOSE LAYERS", Path(r"workspace/20260916-215808-f3b407/decompose/layers_png")),
]


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    for label, rel in TARGETS:
        d = root / rel
        print("===", label, "===")
        if not d.exists():
            print("  (missing)", d)
            continue
        for p in sorted(d.glob("*.png")):
            im = Image.open(p).convert("RGBA")
            a = im.getchannel("A")
            h = a.histogram()
            total = im.width * im.height
            transparent = sum(h[:16]) / total * 100
            opaque = sum(h[240:]) / total * 100
            flag = "  <-- SUSPECT" if opaque > 30 else ""
            print(f"  {p.name:42s} {im.width:4d}x{im.height:<4d} "
                  f"transparent={transparent:5.1f}%  opaque={opaque:5.1f}%{flag}")
        print()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
