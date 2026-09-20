"""导出包自带的离线播放器：生成一个单文件 HTML。

模型、贴图、物理、动画全部内嵌成 data URL，三个渲染库直接内联进页面，
双击就能在浏览器里驱动模型和动画，不依赖任何本地服务。
（模型文件本身也随 zip 提供，供 Cubism Editor 等工具使用。）
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}

_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ - Live2D</title>
<style>
  html, body { margin: 0; height: 100%; background: #14161d; color: #cfd3dc;
    font: 13px/1.5 system-ui, sans-serif; display: flex; flex-direction: column; }
  #wrap { flex: 1; position: relative; min-height: 0; }
  canvas { display: block; width: 100%; height: 100%; }
  #bar { display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 12px;
    background: #1b1e27; border-top: 1px solid #2a2e3a; }
  #bar button { background: #242836; color: #cfd3dc; border: 1px solid #363b4d;
    border-radius: 6px; padding: 5px 12px; cursor: pointer; font-size: 12px; }
  #bar button:hover { border-color: #7b6cff; color: #fff; }
  #bar .tip { color: #6b7180; align-self: center; margin-left: auto; }
</style>
</head>
<body>
<div id="wrap"><canvas id="c"></canvas></div>
<div id="bar"><span class="tip">拖动鼠标可以转头 · 动作按钮：</span></div>
<script>__VENDOR_PIXI__</script>
<script>__VENDOR_CORE__</script>
<script>__VENDOR_DISPLAY__</script>
<script>
"use strict";
const MOTIONS = __MOTIONS__;
const ACCESSORIES = __ACCESSORIES__;
const MODEL_URL = "__MODEL_URL__";
const canvas = document.getElementById("c");
const bar = document.getElementById("bar");
const app = new PIXI.Application({
  view: canvas, backgroundAlpha: 0, antialias: true,
  resizeTo: canvas.parentElement, resolution: window.devicePixelRatio || 1,
});
let model = null;

/* ---- 配件：跟随绑定部件（drawable 质心），weight 控制跟随强度 ---- */
const accSprites = [];
let drIndexMap = null;
function drawableIndexById(core, id) {
  if (!drIndexMap) {
    drIndexMap = {};
    try {
      const n = core.getDrawableCount();
      for (let i = 0; i < n; i++) drIndexMap[core.getDrawableId(i)] = i;
    } catch (e) { return -1; }
  }
  return drIndexMap[id] != null ? drIndexMap[id] : -1;
}
function boneTarget(a) {
  const im = model.internalModel, core = im.coreModel;
  let p = { x: im.width / 2, y: im.height / 2 };   // 默认锚在模型中心
  if (a.anchor) {
    const idx = drawableIndexById(core, a.anchor);
    if (idx >= 0) {
      try {
        const vp = core.getDrawableVertexPositions(idx);
        let cx = 0, cy = 0, n = 0;
        for (let k = 0; k < vp.length; k += 2) { cx += vp[k]; cy += vp[k + 1]; n++; }
        if (n) {
          const ppu = im.pixelsPerUnit || 500;
          p = { x: cx / n * ppu + im.width / 2, y: im.height / 2 - cy / n * ppu };
        }
      } catch (e) {}
    }
  }
  return model.toGlobal(p);
}
function updateAccessories() {
  if (!model || !accSprites.length) return;
  const w = app.renderer.width / app.renderer.resolution;
  const h = app.renderer.height / app.renderer.resolution;
  const cx = w / 2, cy = h / 2;
  for (const { a, spr } of accSprites) {
    const t = boneTarget(a);
    const tx = t.x + (a.dx || 0) * model.scale.x;
    const ty = t.y + (a.dy || 0) * model.scale.y;
    const k = a.weight == null ? 1 : a.weight;
    spr.position.set(cx + (tx - cx) * k, cy + (ty - cy) * k);
    spr.scale.set((a.scale || 1) * model.scale.x);
    spr.rotation = (a.rot || 0) * Math.PI / 180;
    spr.visible = a.show !== false;
  }
}
function setupAccessories() {
  const stage = app.stage;
  for (const a of ACCESSORIES) {
    if (!a.file) continue;
    try {
      const spr = new PIXI.Sprite(PIXI.Texture.from(a.file));
      spr.anchor.set(0.5);
      if (a.front === false) stage.addChildAt(spr, Math.max(0, stage.getChildIndex(model)));
      else stage.addChild(spr);
      accSprites.push({ a, spr });
    } catch (e) {}
  }
  if (accSprites.length) app.ticker.add(updateAccessories);
}

function fit() {
  if (!model) return;
  const w = app.renderer.width / app.renderer.resolution;
  const h = app.renderer.height / app.renderer.resolution;
  const s = Math.min(w / model.internalModel.width, h / model.internalModel.height) * 0.92;
  model.scale.set(s);
  model.position.set(w / 2, (h - model.internalModel.height * s) / 2 + 4);
}
PIXI.live2d.Live2DModel.from(MODEL_URL, { autoInteract: true }).then(m => {
  model = m;
  app.stage.addChild(model);
  model.on("hit", () => {});
  fit();
  setupAccessories();
  window.addEventListener("resize", fit);
  for (const [group, files] of Object.entries(MOTIONS)) {
    (Array.isArray(files) ? files : [files]).forEach((_, i) => {
      const b = document.createElement("button");
      b.textContent = (Array.isArray(files) ? files : [files]).length > 1
        ? group + " " + (i + 1) : group;
      b.onclick = () => model.motion(group, i);
      bar.appendChild(b);
    });
  }
}).catch(e => {
  bar.innerHTML = "";
  const d = document.createElement("div");
  d.style.color = "#e05d5d";
  d.textContent = "模型加载失败：" + (e && e.message || e);
  bar.appendChild(d);
});
</script>
</body>
</html>
"""


def _data_url(bundle: Path, rel: str) -> str:
    """把包内文件转成 data URL；越界或缺失时原样返回相对路径。"""
    root = bundle.resolve()
    p = (bundle / rel).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        return rel
    if not p.is_file():
        return rel
    mime = _MIME.get(p.suffix.lower(), "application/json")
    blob = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{blob}"


def _vendor_script(vendor: Path, name: str) -> str:
    src = (vendor / name).read_text(encoding="utf-8", errors="replace")
    return src.replace("</script>", "<\\/script>")   # 防止内联时提前闭合标签


def build_player_html(bundle: Path, model3_name: str, title: str,
                      vendor_dir: Path) -> str:
    """bundle = 预览目录（含 model3.json）；返回可直接写盘的单文件 HTML。"""
    meta: Dict[str, Any] = json.loads((bundle / model3_name).read_text(encoding="utf-8"))
    fr = meta.get("FileReferences") or {}

    inline = dict(fr)
    if inline.get("Moc"):
        inline["Moc"] = _data_url(bundle, inline["Moc"])
    for key in ("Textures", "Physics", "DisplayInfo", "Pose"):
        if not inline.get(key):
            continue
        if isinstance(inline[key], list):
            inline[key] = [_data_url(bundle, x) for x in inline[key]]
        else:
            inline[key] = _data_url(bundle, inline[key])
    motions: Dict[str, Any] = {}
    for group, files in (fr.get("Motions") or {}).items():
        if isinstance(files, list):
            motions[group] = [_data_url(bundle, m.get("File", ""))
                              for m in files if isinstance(m, dict) and m.get("File")]
    inline["Motions"] = motions

    # 配件（图层编辑剥离 / 手动上传的 PNG）：图片内嵌成 data URL，跟随逻辑
    # 在模板 JS 里复刻（锚点 = 绑定 drawable 的质心，weight 控制跟随强度）
    accessories = []
    for a in _read_accessories(bundle):
        acc = dict(a)
        if acc.get("file"):
            acc["file"] = _data_url(bundle, acc["file"])
        else:
            continue
        accessories.append(acc)

    # 模型 JSON 本身也转 data URL，页面上就不再依赖任何相对路径
    model_url = "data:application/json;base64," + base64.b64encode(
        json.dumps(inline, ensure_ascii=False).encode("utf-8")).decode("ascii")

    html = _TEMPLATE
    html = html.replace("__TITLE__", title)
    html = html.replace("__VENDOR_PIXI__", _vendor_script(vendor_dir, "pixi.min.js"))
    html = html.replace("__VENDOR_CORE__",
                        _vendor_script(vendor_dir, "live2dcubismcore.min.js"))
    html = html.replace("__VENDOR_DISPLAY__",
                        _vendor_script(vendor_dir, "pixi-live2d-display.min.js"))
    html = html.replace("__MOTIONS__", json.dumps(motions, ensure_ascii=False))
    html = html.replace("__ACCESSORIES__", json.dumps(accessories, ensure_ascii=False))
    html = html.replace("__MODEL_URL__", model_url)
    return html


def _read_accessories(bundle: Path) -> list:
    p = bundle / "accessories" / "accessories.json"
    if not p.is_file():
        return []
    try:
        items = json.loads(p.read_text(encoding="utf-8"))
        return items if isinstance(items, list) else []
    except Exception:
        return []
