# -*- coding: utf-8 -*-
"""裁剪浏览器截图的预览区，用于部件开关对比。"""
import sys

from PIL import Image


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    im = Image.open(src)
    # 预览 canvas 大致位于页面右侧 (806,230)-(1246,600)
    crop = im.crop((806, 230, 1246, 600)).resize((880, 740), Image.LANCZOS)
    crop.save(dst)


if __name__ == "__main__":
    main()
