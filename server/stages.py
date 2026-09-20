"""五个阶段的实现。每个阶段独立可跑、可手动上传产物接管。"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from . import config
from .motutil import strip_idle_z
from .progress import make_decompose_progress, make_rig_progress
from .runner import run_cmd
from .tasks import Task

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def _first_image(d: Path) -> Optional[Path]:
    if not d.exists():
        return None
    for p in sorted(d.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMG_EXT:
            return p
    return None


def _gen_mode(task: Task) -> str:
    cfg = config.load()
    return (task.params.get("gen_mode") or cfg.get("gen_mode") or "upload").lower()


# ---------------------------------------------------------------- 1 生图
async def stage_generate(task: Task) -> None:
    sid = "generate"
    outdir = task.stage_dir(sid)
    task.stage_start(sid, "准备生成输入图")

    existing = _first_image(outdir)

    # 显式给了磁盘路径（命令行/测试场景）直接采用
    source_file = task.params.get("source_file")
    if source_file and Path(source_file).exists():
        dst = outdir / ("source" + Path(source_file).suffix.lower())
        if Path(source_file).resolve() != dst.resolve():
            shutil.copy2(source_file, dst)
            existing = dst
    if existing and source_file:
        task.stage_done(sid, "使用已提供的图片", {"source": task.rel_path(existing)})
        return

    mode = _gen_mode(task)
    # 「从此步重跑」第 1 步 = 真的要重画一张，不能把上一张当结果交回去，
    # 否则用户以为在重生图、看到的还是旧图。upload 模式无图可生，仍沿用。
    if existing and not (task.rerun_from == sid and mode != "upload"):
        task.stage_done(sid, "使用已提供的图片", {"source": task.rel_path(existing)})
        return

    if mode == "upload":
        raise RuntimeError("请上传一张立绘，或在设置里切换生图方式")

    prompt = (task.params.get("prompt") or "").strip()
    cfg = config.load()
    full_prompt = f"{prompt}, {cfg['positive_suffix']}".strip(", ") if prompt else ""
    if not full_prompt:
        raise RuntimeError("缺少生图提示词")

    if existing:
        # 重画前清掉旧图：否则下面的 _first_image 会把上一张当成本次结果
        for p in sorted(outdir.rglob("*")):
            if p.is_file() and p.suffix.lower() in IMG_EXT:
                p.unlink(missing_ok=True)
        task.log("重跑生图：已清除上一轮产物", "info", sid)

    if mode == "comfyui":
        await _generate_comfyui(task, cfg, full_prompt, outdir)
    elif mode == "api":
        await _generate_api(task, cfg, full_prompt, outdir)
    else:
        raise RuntimeError(f"未知生图模式：{mode}")

    img = _first_image(outdir)
    if not img:
        raise RuntimeError("生图完成但没有落盘图片")
    task.stage_done(sid, "生图完成", {"source": task.rel_path(img)})


async def _generate_comfyui(task: Task, cfg: dict, prompt: str, outdir: Path) -> None:
    base_url = (cfg.get("comfyui_url") or "").rstrip("/")
    wf_raw = task.params.get("workflow") or cfg.get("comfyui_workflow") or ""
    if not base_url:
        raise RuntimeError("未配置 ComfyUI 地址（设置 → 生图）")
    if not wf_raw:
        raise RuntimeError("未提供 ComfyUI workflow（API format JSON）")
    try:
        wf = json.loads(wf_raw)
    except Exception as e:
        raise RuntimeError(f"workflow JSON 解析失败：{e}")

    negative = cfg.get("negative_prompt", "")
    seed = int(task.params.get("seed") or 0) or _rand_seed()
    replaced = 0
    for node in wf.values():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type")
        inputs = node.get("inputs") or {}
        if ct == "CLIPTextEncode" and isinstance(inputs.get("text"), str):
            title = str(node.get("_meta", {}).get("title", "")).lower()
            if "neg" in title:
                inputs["text"] = negative
                replaced += 1
            elif "pos" in title or not replaced:
                inputs["text"] = prompt
                replaced += 1
        elif "seed" in inputs:
            inputs["seed"] = seed
    if replaced == 0:
        task.log("未在 workflow 中找到 CLIPTextEncode 节点，提示词可能未被替换", "warn", "generate")

    task.log(f"提交 ComfyUI 任务 seed={seed}", "info", "generate")
    task.stage_progress("generate", 15, "已提交 ComfyUI")

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            r = await client.post(f"{base_url}/prompt", json={"prompt": wf})
            r.raise_for_status()
            pid = r.json().get("prompt_id")
        except Exception as e:
            raise RuntimeError(f"ComfyUI 调用失败：{e}")
        if not pid:
            raise RuntimeError("ComfyUI 未返回 prompt_id")

        for i in range(600):
            await asyncio.sleep(2)
            try:
                hist = (await client.get(f"{base_url}/history/{pid}")).json()
            except Exception:
                continue
            entry = (hist or {}).get(pid)
            if not entry:
                continue
            imgs = _extract_comfy_images(entry, base_url)
            if imgs:
                task.stage_progress("generate", 80, f"取回 {len(imgs)} 张")
                for idx, item in enumerate(imgs):
                    blob = (await client.get(item["url"], timeout=120)).content
                    (outdir / ("source.png" if idx == 0 else f"source_{idx}.png")).write_bytes(blob)
                return
            if i % 10 == 0:
                task.stage_progress("generate", min(75, 15 + i // 6), "等待 ComfyUI 出图…")
    raise RuntimeError("ComfyUI 超时未完成（20 分钟）")


def _extract_comfy_images(entry: dict, base_url: str) -> List[dict]:
    out: List[dict] = []
    for node in (entry.get("outputs") or {}).values():
        for key in ("images", "gifs", "files"):
            for it in (node.get(key) or []):
                if isinstance(it, dict) and it.get("filename"):
                    from urllib.parse import urlencode

                    q = {"filename": it["filename"]}
                    if it.get("subfolder"):
                        q["subfolder"] = it["subfolder"]
                    if it.get("type"):
                        q["type"] = it["type"]
                    out.append({"url": f"{base_url}/view?" + urlencode(q)})
    return out


def _rand_seed() -> int:
    import random
    return random.randint(1, 2 ** 31 - 1)


async def _generate_api(task: Task, cfg: dict, prompt: str, outdir: Path) -> None:
    base = (cfg.get("api_base") or "").rstrip("/")
    if not base:
        raise RuntimeError("未配置生图 API 地址（设置 → 生图）")
    key = cfg.get("api_key") or ""
    model = cfg.get("api_model") or ""
    size = task.params.get("size") or "1024x1536"
    payload: Dict[str, Any] = {"prompt": prompt, "n": 1, "size": size,
                               "response_format": "b64_json"}
    if model:
        payload["model"] = model
    if cfg.get("negative_prompt"):
        payload["negative_prompt"] = cfg["negative_prompt"]

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    task.stage_progress("generate", 20, "调用生图 API")
    async with httpx.AsyncClient(timeout=600) as client:
        try:
            r = await client.post(f"{base}/images/generations", json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"生图 API 返回 {e.response.status_code}：{e.response.text[:200]}")
        except Exception as e:
            raise RuntimeError(f"生图 API 调用失败：{e}")

    items = data.get("data") or []
    if not items:
        raise RuntimeError(f"API 未返回图片：{str(data)[:300]}")
    saved = 0
    for idx, it in enumerate(items):
        blob = b""
        if it.get("b64_json"):
            blob = base64.b64decode(it["b64_json"])
        elif it.get("url"):
            async with httpx.AsyncClient(timeout=180) as c2:
                blob = (await c2.get(it["url"])).content
        if not blob:
            continue
        (outdir / ("source.png" if idx == 0 else f"source_{idx}.png")).write_bytes(blob)
        saved += 1
    if not saved:
        raise RuntimeError("API 返回数据无法解析成图片")


# ---------------------------------------------------------------- 2 预处理
async def stage_preprocess(task: Task) -> None:
    sid = "preprocess"
    task.stage_start(sid, "预处理")
    outdir = task.stage_dir(sid)

    src_rel = task.stages["generate"]["artifacts"].get("source")
    src = None
    if src_rel:
        src = task.dir / src_rel
        if not src.exists():
            src = None
    if src is None:
        src = _first_image(task.stage_dir("generate"))
    if src is None:
        raise RuntimeError("找不到生图产物，请先完成第 1 步或手动上传")

    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("缺少 Pillow，请 .venv\\Scripts\\python.exe -m pip install pillow")

    method = task.params.get("preprocess_method") or "crop"
    work = src
    if method == "rembg":
        task.stage_progress(sid, 20, "调用 rembg 去背景")
        try:
            import rembg  # noqa: F401  仅探测
        except ImportError:
            raise RuntimeError("未安装 rembg，或改用「仅裁切」预处理")
        nobg = outdir / "nobg.png"
        cmd = [config.python_exe(), "-m", "rembg", "i",
               "-m", config.get("rembg_model") or "isnet-general-use",
               str(src), str(nobg)]
        rc = await run_cmd(task, cmd, stage=sid, timeout=1800)
        if rc != 0 or not nobg.exists():
            raise RuntimeError("rembg 去背景失败")
        work = nobg

    task.stage_progress(sid, 70, "裁边并居中")
    img = Image.open(work).convert("RGBA")
    alpha = img.split()[-1]
    bbox = alpha.getbbox()
    if bbox and (bbox[2] - bbox[0]) > 8 and (bbox[3] - bbox[1]) > 8:
        img = img.crop(bbox)
    w, h = img.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - w) // 2, (side - h) // 2), img)
    dst = outdir / "clean.png"
    canvas.save(dst)

    task.stage_done(sid, "预处理完成", {"clean": task.rel_path(dst)})


# ---------------------------------------------------------------- 3 分层
async def stage_decompose(task: Task) -> None:
    sid = "decompose"
    task.stage_start(sid, "准备分层")
    outdir = task.stage_dir(sid)
    cfg = config.load()
    started_at = time.time()

    repo = config.resolve_tool("see_through_path")
    if not repo or not Path(repo).exists():
        raise RuntimeError("未配置 see-through 仓库路径（设置 → 外部工具）")
    repo = Path(repo)
    script_dir = repo / "inference" / "scripts"
    if not (script_dir / "inference_psd.py").exists():
        raise RuntimeError(f"未在 {script_dir} 找到 inference_psd.py，确认仓库完整")

    src_rel = task.stages["preprocess"]["artifacts"].get("clean")
    src = (task.dir / src_rel) if src_rel else None
    if not src or not src.exists():
        src = _first_image(task.stage_dir("preprocess")) or _first_image(task.stage_dir("generate"))
    if not src:
        raise RuntimeError("找不到预处理产物，请先完成第 2 步")

    vram = config.vram_gb()
    sug = _suggest(vram)
    precision = task.params.get("decomp_precision") or cfg.get("decomp_precision") or "auto"
    if precision == "auto":
        precision = sug["precision"]
    resolution = int(task.params.get("decomp_resolution") or cfg.get("decomp_resolution") or 1024)
    depth_res = int(task.params.get("decomp_depth_resolution")
                    or cfg.get("decomp_depth_resolution") or 768)
    steps = int(task.params.get("decomp_steps") or cfg.get("decomp_steps") or 30)
    offload = bool(task.params.get("decomp_group_offload", cfg.get("decomp_group_offload")))

    script = "inference_psd_quantized.py" if precision == "nf4" else "inference_psd.py"
    if precision == "nf4" and not (script_dir / script).exists():
        raise RuntimeError("未找到量化脚本 inference_psd_quantized.py")

    # 注意参数名不同：量化脚本 --num_inference_steps，非量化 --inference_steps
    cmd = [config.python_exe(), str(script_dir / script),
           "--srcp", str(src), "--save_to_psd",
           "--resolution", str(resolution),
           "--resolution_depth", str(depth_res)]
    if precision == "nf4":
        cmd += ["--num_inference_steps", str(steps)]
        # NF4（bitsandbytes 4bit 层）与 group_offload 不兼容，会报
        # CUBLAS_STATUS_NOT_INITIALIZED；且 NF4 本身已足够省显存
        cmd.append("--no_group_offload")
    else:
        cmd += ["--inference_steps", str(steps)]
        if offload:
            cmd.append("--group_offload")

    task.log(f"显存 {vram}GB → precision={precision} res={resolution} steps={steps} "
             f"depth_res={depth_res} offload={offload}", "info", sid)

    rc = await run_cmd(
        task, cmd, cwd=str(repo), stage=sid, timeout=7200,
        on_line=make_decompose_progress(),
        env_extra={
            "PYTHONPATH": str(repo / "common") + os.pathsep + str(repo / "annotators"),
            # 减少显存碎片，8GB 卡跑 1024 分辨率时必开
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
            # Marigold 推理按批喂图（21 张整批会 OOM，见 tools 补丁说明）
            "L2D_DEPTH_BATCH": "3",
        })
    if rc != 0:
        raise RuntimeError(f"See-through 分层失败，退出码 {rc}")

    psd_out = _pick_fresh_psd(repo, started_at)
    if not psd_out:
        raise RuntimeError("未找到本次运行输出的 .psd（只认分层开始之后生成的文件），"
                           "检查 see-through 是否正常运行")

    dst_psd = outdir / "layers.psd"
    shutil.copy2(psd_out, dst_psd)
    artifacts: Dict[str, str] = {"psd": task.rel_path(dst_psd)}

    try:
        from psd_tools import PSDImage  # type: ignore

        task.stage_progress(sid, 92, "导出图层预览")
        layers_dir = outdir / "layers_png"
        layers_dir.mkdir(exist_ok=True)
        psd = PSDImage.open(dst_psd)
        n = 0
        for i, layer in enumerate(psd):
            try:
                im = layer.composite()
                if im is None:
                    continue
                name = re.sub(r"[^\w\u4e00-\u9fff.-]", "_", layer.name)[:40] or f"layer{i}"
                im.convert("RGBA").save(layers_dir / f"{i:02d}_{name}.png")
                n += 1
            except Exception:
                continue
        task.log(f"导出 {n} 个图层预览", "ok", sid)
        artifacts["layers_dir"] = task.rel_path(layers_dir)
    except ImportError:
        task.log("未安装 psd-tools，跳过图层预览导出", "warn", sid)
    except Exception as e:
        task.log(f"图层预览导出失败：{e}", "warn", sid)

    task.stage_done(sid, "分层完成", artifacts)


def _pick_fresh_psd(repo: Path, started_at: float) -> Optional[Path]:
    """在 see-through 的输出目录里找本次运行生成的 PSD。

    只认 mtime 不早于本阶段开始时间的文件 —— 输出目录里可能躺着以前
    跑的旧 PSD，按「最新 mtime」裸捡会把旧产物误当本次结果。
    同一次会输出 clean.psd 和 clean_depth.psd，优先取非 depth 的主产物。
    """
    candidates = [repo / "workspace" / "layerdiff_output",
                  repo / "layerdiff_output",
                  Path.cwd() / "workspace" / "layerdiff_output"]
    best: Optional[Path] = None
    best_key = None
    for c in candidates:
        if not c.exists():
            continue
        for p in c.glob("*.psd"):
            if p.stat().st_mtime < started_at - 5:
                continue
            is_depth = "depth" in p.stem.lower()
            key = (0 if not is_depth else 1, -p.stat().st_mtime)
            if best_key is None or key < best_key:
                best, best_key = p, key
    return best


def _suggest(vram: Optional[float]) -> Dict[str, Any]:
    """按显存推荐分层参数（与 envcheck 里对外的口径一致）。"""
    if vram is None:
        return {"precision": "bf16", "resolution": 1024, "group_offload": True}
    if vram >= 15:
        return {"precision": "bf16", "resolution": 1280, "group_offload": False}
    if vram >= 11:
        return {"precision": "bf16", "resolution": 1024, "group_offload": True}
    # <11GB 走 NF4，而 NF4 必须关 group_offload（与 bnb 4bit 冲突）
    return {"precision": "nf4", "resolution": 1024, "group_offload": False}


# ---------------------------------------------------------------- 4 绑骨
async def stage_rig(task: Task) -> None:
    sid = "rig"
    task.stage_start(sid, "准备绑骨")
    outdir = task.stage_dir(sid)

    repo = config.resolve_tool("image2live2d_path")
    if not repo or not Path(repo).exists():
        raise RuntimeError("未配置 image2live2d 仓库路径（设置 → 外部工具）")
    repo = Path(repo)

    psd_rel = task.stages["decompose"]["artifacts"].get("psd")
    psd = (task.dir / psd_rel) if psd_rel else None
    if not psd or not psd.exists():
        cand = sorted(task.stage_dir("decompose").glob("*.psd"))
        psd = cand[0] if cand else None
    if not psd or not psd.exists():
        raise RuntimeError("找不到分层 .psd，请先完成第 3 步或手动上传")

    inp_out = outdir / "character.inp"
    # image2live2d 的 -o 路径如果指向已存在的目录会报 WinError 5
    if inp_out.exists() and inp_out.is_dir():
        raise RuntimeError(f"{inp_out} 是目录，请先重置第 4 步")
    cmd = [config.python_exe(), "-m", "image2live2d", "--psd", str(psd), "-o", str(inp_out)]
    if task.params.get("rig_emit_live2d", config.get("rig_emit_live2d", True)):
        cmd += ["--live2d", str(outdir / "live2d")]

    rc = await run_cmd(task, cmd, cwd=str(repo), stage=sid, timeout=3600,
                       on_line=make_rig_progress(),
                       env_extra={"PYTHONPATH": str(repo / "src")})
    if rc != 0:
        raise RuntimeError(f"image2live2d 绑骨失败，退出码 {rc}")

    moc3s = sorted(outdir.rglob("*.moc3"))
    if not moc3s:
        raise RuntimeError("未生成 .moc3，检查 PSD 图层命名或工具 QA 报告")

    task.stage_done(sid, f"生成 {len(moc3s)} 个模型",
                    {"moc3": task.rel_path(moc3s[0])})


# ---------------------------------------------------------------- 5 预览
async def stage_preview(task: Task) -> None:
    sid = "preview"
    task.stage_start(sid, "整理模型包")
    outdir = task.stage_dir(sid)

    moc3s = sorted(task.stage_dir("rig").rglob("*.moc3"))
    if not moc3s:
        raise RuntimeError("第 4 步没有 .moc3 产物")
    model_root = moc3s[0].parent
    if outdir.resolve() != model_root.resolve():
        # 整目录递归拷贝：textures/ 等子目录漏掉会导致网页预览贴图 404
        shutil.copytree(model_root, outdir, dirs_exist_ok=True)

    model_json = None
    # 常规模型是 <名字>.model3.json；也兜底认一下裸的 model3.json（社区工具偶见）
    for pattern in ("*.model3.json", "*.model.json", "model3.json"):
        found = sorted(outdir.glob(pattern))
        if found:
            model_json = found[0]
            break
    if not model_json:
        raise RuntimeError("缺少 model3.json，无法预览")

    # 自动生成的待机动作带 Z 轴（面内旋转）曲线，2D 网格转起来会整体扭曲，
    # 打包时直接剔除（幂等，已剔除过的文件不受影响）
    try:
        strip_idle_z(model_json)
    except Exception:
        pass

    try:
        meta = json.loads(model_json.read_text(encoding="utf-8"))
        name = meta.get("Name") or model_json.stem
        motions = list((meta.get("FileReferences") or {}).get("Motions", {}).keys())
    except Exception as e:
        raise RuntimeError(f"model3.json 解析失败：{e}")

    task.stage_done(sid, f"模型就绪：{name}", {
        "model_json": task.rel_path(model_json),
        "model_root": task.rel_path(outdir),
        "name": name,
        "motions": motions,
    })
