# -*- coding: utf-8 -*-
"""修复被写坏的 UTF-8 字节（em-dash 序列的第三字节变成了 '?'）。"""
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "tools" / "image2live2d" / "src" / "image2live2d" / "core" / "structure" / "__init__.py"
b = p.read_bytes()
before = len(b)
fixed = b.replace(b"\xe2\x80?", b"-")
p.write_bytes(fixed)
print("bytes:", before, "->", len(fixed))
print(fixed[:100])
