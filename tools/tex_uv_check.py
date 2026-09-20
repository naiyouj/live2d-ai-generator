# -*- coding: utf-8 -*-
"""贴图内容 UV 范围 vs moc3 网格 UV 范围对照；排查某块贴图为什么花掉。

用法：
    python tools\\tex_uv_check.py [preview/textures 目录]
不传参数时用脚本里默认的任务目录（按需改 NAMES / MESH_UV）。
"""
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TEX = Path(sys.argv[1]) if len(sys.argv) > 1 \
    else ROOT / "workspace/20260916-215808-f3b407/preview/textures"

NAMES = [
    "003_tex_02_face_base",
    "006_tex_03_neck",
    "013_tex_08_clothing",
    "015_tex_09_clothing",
    "021_tex_13_mouth",
]

# 浏览器端读到的网格 UV 范围 (u0,v0,u1,v1)，v 以贴图左上为原点
MESH_UV = {
    "02_face_base": [0.449, 0.813, 0.550, 0.921],
    "03_neck":      [0.482, 0.778, 0.517, 0.842],
    "13_mouth":     [0.483, 0.818, 0.513, 0.840],
}


def main() -> None:
    print("texture content bbox vs mesh uv box:")
    for name in NAMES:
        im = Image.open(TEX / f"{name}.png").convert("RGBA")
        bbox = im.getchannel("A").getbbox()
        if not bbox:
            print(f"  {name}: EMPTY")
            continue
        u = (bbox[0] / 1024, bbox[1] / 1024, bbox[2] / 1024, bbox[3] / 1024)
        print(f"  {name}: content uv x[{u[0]:.3f},{u[2]:.3f}] y[{u[1]:.3f},{u[3]:.3f}]")
    for k, v in MESH_UV.items():
        print(f"  mesh {k:14s}: uv x[{v[0]:.3f},{v[2]:.3f}] y[{v[1]:.3f},{v[3]:.3f}]")


if __name__ == "__main__":
    main()
