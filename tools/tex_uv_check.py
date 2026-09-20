# -*- coding: utf-8 -*-
"""贴图内容 UV 范围 vs moc3 网格 UV 范围对照；放大用户截图的方块区域。"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TEX = ROOT / "workspace/20260916-215808-f3b407/preview/textures"

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

    src = Path(r"C:\Users\Administrator\.zcode\cli\image-cache"
               r"\sess_9fce5468-8521-4dcf-b7fe-013aa7fec9bc"
               r"\image-4177e265f4a46824c8861341aa229085.png")
    if src.exists():
        im = Image.open(src)
        print("user img size:", im.size)
        im.crop((110, 60, 230, 180)).resize(
            (480, 480), Image.NEAREST).save(r"C:\Users\Administrator\AppData\Local\Temp\user_square_zoom.png")


if __name__ == "__main__":
    main()
