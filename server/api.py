"""全部 HTTP 接口：任务 CRUD / 执行 / 上传接管 / 文件 / WebSocket，系统级环境与配置。"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import (APIRouter, File, HTTPException, Query, UploadFile,
                     WebSocket, WebSocketDisconnect)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import config
from .envcheck import VENDOR_SOURCES, full_report
from .motutil import strip_idle_z
from .player import build_player_html
from .tasks import STAGES, STAGE_IDS, JobBusyError, jobs, manager

# 语义文件名 -> 对应阶段（upload 接管时用来落位/标记完成）
STAGE_OF_ARTIFACT = {"generate": "source", "preprocess": "clean",
                     "decompose": "psd", "rig": "moc3"}
# 能手动接管的阶段。预览只是把第 4 步的产物整理成模型包，没有可上传的产物形态
UPLOADABLE_STAGES = ("generate", "preprocess", "decompose", "rig")

tasks_router = APIRouter(prefix="/api/tasks", tags=["tasks"])
system_router = APIRouter(prefix="/api", tags=["system"])


# ================================================================ 任务接口
class CreateBody(BaseModel):
    name: str = ""
    prompt: str = ""
    params: Dict[str, Any] = {}
    run: bool = True
    from_stage: Optional[str] = None


class RunBody(BaseModel):
    from_stage: Optional[str] = None
    skip_done: bool = False


@tasks_router.get("")
async def list_tasks() -> List[Dict[str, Any]]:
    return manager.list()


@tasks_router.get("/stages")
async def stage_defs() -> List[Dict[str, str]]:
    return STAGES


@tasks_router.get("/{task_id}")
async def get_task(task_id: str) -> Dict[str, Any]:
    t = _need(task_id)
    return t.to_dict()


@tasks_router.post("")
async def create_task(body: CreateBody) -> Dict[str, Any]:
    params = dict(body.params)
    if body.prompt:
        params["prompt"] = body.prompt
    t = manager.create(body.name or body.prompt[:30] or "新任务", params)
    queue_pos = None
    if body.run:
        queue_pos = await _start(t, body.from_stage)
    return {"id": t.id, "task": t.to_dict(), "queue": queue_pos}


@tasks_router.delete("/{task_id}")
async def delete_task(task_id: str) -> Dict[str, Any]:
    _need(task_id)
    jobs.cancel(task_id)
    if not manager.remove(task_id):
        raise HTTPException(404, "任务不存在")
    return {"ok": True}


@tasks_router.post("/{task_id}/cancel")
async def cancel_task(task_id: str) -> Dict[str, Any]:
    t = _need(task_id)
    jobs.cancel(task_id)
    t.status = "cancelled"
    for sid in STAGE_IDS:
        if t.stages[sid]["status"] == "running":
            t.stage_error(sid, "已取消")
    t.save()
    return {"ok": True}


@tasks_router.post("/{task_id}/run")
async def run_task(task_id: str, body: RunBody) -> Dict[str, Any]:
    t = _need(task_id)
    if body.from_stage and body.from_stage not in STAGE_IDS:
        raise HTTPException(400, "阶段不存在")
    t.params["skip_done"] = body.skip_done
    queue_pos = await _start(t, body.from_stage)
    return {"ok": True, "id": task_id, "queue": queue_pos}


@tasks_router.post("/{task_id}/reset/{stage}")
async def reset_stage(task_id: str, stage: str) -> Dict[str, Any]:
    t = _need(task_id)
    if stage not in STAGE_IDS:
        raise HTTPException(400, "阶段不存在")
    jobs.cancel(task_id)
    for sid in STAGE_IDS[STAGE_IDS.index(stage):]:
        p = t.stage_dir(sid)
        for f in p.iterdir():
            if f.is_file():
                f.unlink(missing_ok=True)
            else:
                shutil.rmtree(f, ignore_errors=True)
        t.stages[sid].update(status="pending", progress=0, message="", outputs=[],
                             artifacts={}, started_at=None, finished_at=None)
        t._broadcast({"type": "stage", "task": t.id, "data": dict(t.stages[sid])})
    t.status = "idle"
    t.error = None
    t.save()
    return {"ok": True, "task": t.to_dict()}


@tasks_router.post("/{task_id}/input/{stage}")
async def upload_input(task_id: str, stage: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    """手动上传产物接管某个阶段（跳过没装的工具，或替换中间结果）。"""
    t = _need(task_id)
    if stage not in STAGE_IDS:
        raise HTTPException(400, "阶段不存在")
    if stage not in UPLOADABLE_STAGES:
        raise HTTPException(400, "预览阶段是打包动作，没有可上传的产物；"
                                 "要换模型请在第 4 步传 .moc3 或模型包 zip")
    d = t.stage_dir(stage)
    data = await file.read()
    name = Path(file.filename or "upload.bin").name

    if stage == "rig":
        models = d / "live2d"
        models.mkdir(parents=True, exist_ok=True)
        low = name.lower()
        if low.endswith(".zip"):
            # 第 4 步的产物是一整个模型包（.moc3 + model3.json + textures/），
            # 单文件传不全，所以支持直接把整个模型目录打成的 zip 丢进来
            names = _unzip_into(data, models)
            if not any(n.lower().endswith(".moc3") for n in names):
                raise HTTPException(400, "zip 里没有 .moc3，确认打包的是整个模型目录")
        elif low.endswith(".moc3"):
            (models / name).write_bytes(data)
        else:
            raise HTTPException(400, "第 4 步只能传 .moc3，或整个模型目录打成的 .zip")
        moc3s = sorted(models.rglob("*.moc3"))
        if not moc3s:
            raise HTTPException(400, "上传内容里没有 .moc3，确认打包的是整个模型目录")
        saved = moc3s[0]
    else:
        saved = d / name
        saved.write_bytes(data)

    key = STAGE_OF_ARTIFACT.get(stage)
    if key:
        t.stages[stage]["artifacts"][key] = t.rel_path(saved)
    t.log(f"手动上传 {name} 到 {stage}", "ok", stage)
    t.stages[stage].update(status="done", progress=100,
                           message=f"手动上传 {name}", finished_at=time.time())
    t._scan_outputs(stage)
    t._broadcast({"type": "stage", "task": t.id, "data": dict(t.stages[stage])})
    t.save()
    return {"ok": True, "path": t.rel_path(saved), "task": t.to_dict()}


@tasks_router.get("/{task_id}/files/{relpath:path}")
async def serve_file(task_id: str, relpath: str):
    """按相对路径提供任务产物（模型内部资源按相对 URL 解析，必须走这个）。"""
    t = _need(task_id)
    target = _safe_join(t.dir, relpath)
    if not target.is_file():
        raise HTTPException(404, "文件不存在")
    media = None
    if target.suffix.lower() == ".json":
        media = "application/json"
    elif target.suffix.lower() in (".moc3", ".inp"):
        media = "application/octet-stream"
    return FileResponse(target, media_type=media)


@tasks_router.websocket("/{task_id}/ws")
async def ws_logs(ws: WebSocket, task_id: str) -> None:
    await ws.accept()
    t = manager.get(task_id)
    if not t:
        await ws.send_json({"type": "error", "data": "任务不存在"})
        await ws.close()
        return
    q = t.subscribe()
    await ws.send_json({"type": "snapshot", "data": t.to_dict()})
    try:
        while True:
            payload = await q.get()
            await ws.send_json(payload)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception:
        pass
    finally:
        t.unsubscribe(q)


# ================================================================ 动画接口
# 自定义动画存在预览目录，命名 <前缀>.<safe_name>.motion3.json（前缀取 model3
# 文件名，与工具自动生成的动画同目录同规格），model3.json 的 Motions 会同步登记
# 到 "Custom" 组，Cubism Editor 打开模型包也能直接看到。
CUSTOM_GROUP = "Custom"
MOTION_PREFIX_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\- ]{0,39}$")


def _preview_model3(t) -> Optional[Path]:
    """任务预览目录里的 model3.json（不存在返回 None）。"""
    outdir = t.stage_dir("preview")
    for pattern in ("*.model3.json", "*.model.json", "model3.json"):
        found = sorted(outdir.glob(pattern))
        if found:
            return found[0]
    return None


def _read_model3(t) -> Path:
    p = _preview_model3(t)
    if not p:
        raise HTTPException(400, "该任务还没有可用的模型（先完成第 5 步预览）")
    return p


def _safe_motion_name(name: str) -> str:
    name = (name or "").strip()
    if not MOTION_PREFIX_RE.match(name):
        raise HTTPException(400, "动作名只能用中英文、数字和 -_ . 空格，长度 1-40")
    return name


def _model3_stem(model3: Path) -> str:
    """character.model3.json -> character（自定义动画文件名的公共前缀）。"""
    stem = model3.name
    for suf in (".model3.json", ".model.json"):
        if stem.endswith(suf):
            return stem[: -len(suf)]
    return stem


def _motion_file(t, name: str) -> Path:
    model3 = _read_model3(t)
    # 与工具自动生成的 character.idle.motion3.json 同目录、同命名规格
    return model3.parent / f"{_model3_stem(model3)}.{name}.motion3.json"


def _scan_motions(model3: Path) -> List[Dict[str, Any]]:
    """model3.json 的 Motions 摊平成 [{group,name,file}]，file 为相对预览目录路径。

    name 去掉了 <模型名>. 前缀（character.idle -> idle），界面展示与删除接口
    都用这个短名；保存/删除时由 _motion_file 补回前缀。"""
    meta = json.loads(model3.read_text(encoding="utf-8"))
    stem = _model3_stem(model3)
    out = []
    for group, files in (meta.get("FileReferences", {}).get("Motions") or {}).items():
        for m in files or []:
            if isinstance(m, dict) and m.get("File"):
                base = Path(m["File"]).name.replace(".motion3.json", "")
                if base.startswith(stem + "."):
                    base = base[len(stem) + 1:]
                out.append({"group": group, "name": base, "file": m["File"]})
    return out


class MotionSaveBody(BaseModel):
    name: str
    motion: Dict[str, Any]      # 完整 motion3.json 结构


@tasks_router.get("/{task_id}/motions")
async def list_motions(task_id: str) -> Dict[str, Any]:
    """列出模型全部动作：模型自带 + 用户自建，自建的带 editable 标记。"""
    t = _need(task_id)
    model3 = _read_model3(t)
    custom = {m["name"] for m in _scan_motions(model3)
              if m["group"] == CUSTOM_GROUP}
    return {"motions": [
        {**m, "editable": m["name"] in custom}
        for m in _scan_motions(model3)
    ]}


@tasks_router.post("/{task_id}/motions")
async def save_motion(task_id: str, body: MotionSaveBody) -> Dict[str, Any]:
    """保存/覆盖一个自定义动作：写 motion3.json 并登记进 model3.json。"""
    t = _need(task_id)
    name = _safe_motion_name(body.name)
    model3 = _read_model3(t)
    mf = _motion_file(t, name)

    try:
        blob = json.dumps(body.motion, ensure_ascii=False, indent=2)
        meta = json.loads(blob)      # 顺带校验是合法 JSON 对象
        if not isinstance(meta.get("Curves"), list):
            raise ValueError("缺少 Curves")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"动画数据不合法：{e}")

    mf.write_text(blob, encoding="utf-8")

    m3 = json.loads(model3.read_text(encoding="utf-8"))
    motions = m3.setdefault("FileReferences", {}).setdefault("Motions", {})
    group = motions.setdefault(CUSTOM_GROUP, [])
    rel = mf.name
    if not any(m.get("File") == rel for m in group):
        group.append({"File": rel})
    model3.write_text(json.dumps(m3, ensure_ascii=False, indent=2), encoding="utf-8")

    t.log(f"保存动作 {name}", "ok", "preview")
    t.stage_dir("preview")           # 确保目录在（._scan_outputs 用）
    t._scan_outputs("preview")
    t._broadcast({"type": "stage", "task": t.id, "data": dict(t.stages["preview"])})
    return {"ok": True, "name": name, "file": t.rel_path(mf),
            "motions": _scan_motions(model3)}


@tasks_router.delete("/{task_id}/motions/{name}")
async def delete_motion(task_id: str, name: str) -> Dict[str, Any]:
    """删除自定义动作（只删 Custom 组的，工具自带的不可删）。"""
    t = _need(task_id)
    name = _safe_motion_name(name)
    model3 = _read_model3(t)
    # 兼容带模型前缀的名字（character.nod / nod 都认）
    stem = _model3_stem(model3)
    if name.startswith(stem + "."):
        name = name[len(stem) + 1:]
    mf = _motion_file(t, name)

    m3 = json.loads(model3.read_text(encoding="utf-8"))
    motions = m3.get("FileReferences", {}).get("Motions") or {}
    group = motions.get(CUSTOM_GROUP) or []
    if not any(m.get("File") == mf.name for m in group):
        raise HTTPException(404, "该动作不存在或不是自建动作")
    motions[CUSTOM_GROUP] = [m for m in group if m.get("File") != mf.name]
    if not motions[CUSTOM_GROUP]:
        motions.pop(CUSTOM_GROUP)
    model3.write_text(json.dumps(m3, ensure_ascii=False, indent=2), encoding="utf-8")
    mf.unlink(missing_ok=True)

    t.log(f"删除动作 {name}", "info", "preview")
    t._scan_outputs("preview")
    t._broadcast({"type": "stage", "task": t.id, "data": dict(t.stages["preview"])})
    return {"ok": True, "motions": _scan_motions(model3)}


# ================================================================ 模型微调接口
# 贴图重绘 / 配件 / 自定义骨骼都落在预览目录里，随模型包一起导出：
#   accessories/accessories.json + accessories/<名字>.png   配件
#   custom_bones.json                                       自定义骨骼
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
_DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|webp);base64,(.+)$", re.S)


def _edit_root(t) -> Path:
    """可编辑资源的根目录 = 预览目录（模型包本体）。"""
    return _read_model3(t).parent


class ItemsBody(BaseModel):
    items: List[Dict[str, Any]]


class BonesBody(BaseModel):
    bones: List[Dict[str, Any]]


class TexSaveBody(BaseModel):
    path: str
    image: str                  # data URL（image/png）


@tasks_router.post("/{task_id}/fix-idle")
async def fix_idle(task_id: str) -> Dict[str, Any]:
    """手动触发：剔除待机动作的 Z 轴（面内旋转）曲线。幂等。"""
    t = _need(task_id)
    model3 = _read_model3(t)
    n = strip_idle_z(model3)
    if n:
        t.log(f"待机动作剔除 {n} 条 Z 轴曲线", "ok", "preview")
    return {"ok": True, "changed": n}


@tasks_router.post("/{task_id}/textures/save")
async def save_texture(task_id: str, body: TexSaveBody) -> Dict[str, Any]:
    """把图片编辑器画布内容写回贴图文件（只允许覆盖模型包内已有贴图）。"""
    t = _need(task_id)
    root = _edit_root(t)
    target = _safe_join(root, body.path)
    if target.suffix.lower() not in IMAGE_EXT:
        raise HTTPException(400, "只能覆盖图片文件")
    if not target.is_file():
        raise HTTPException(404, "贴图不存在，不能新建文件")
    m = _DATA_URL_RE.match(body.image or "")
    if not m:
        raise HTTPException(400, "图片数据格式不对（需要 data:image/png;base64,...）")
    import base64 as _b64
    try:
        data = _b64.b64decode(m.group(2), validate=True)
    except Exception as e:
        raise HTTPException(400, f"base64 解码失败：{e}")
    target.write_bytes(data)
    t.log(f"贴图已编辑保存 {target.name}（{len(data) // 1024}KB）", "ok", "preview")
    t._scan_outputs("preview")
    t._broadcast({"type": "stage", "task": t.id, "data": dict(t.stages["preview"])})
    return {"ok": True, "path": t.rel_path(target)}


@tasks_router.get("/{task_id}/accessories")
async def list_accessories(task_id: str) -> Dict[str, Any]:
    t = _need(task_id)
    return {"items": _read_accessories(_edit_root(t))}


@tasks_router.put("/{task_id}/accessories")
async def put_accessories(task_id: str, body: ItemsBody) -> Dict[str, Any]:
    """整体保存配件列表（前端是列表的唯一编辑者，直接整份覆写）。"""
    t = _need(task_id)
    root = _edit_root(t)
    acc_dir = root / "accessories"
    acc_dir.mkdir(parents=True, exist_ok=True)
    (acc_dir / "accessories.json").write_text(
        json.dumps(body.items, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "count": len(body.items)}


@tasks_router.post("/{task_id}/accessories")
async def upload_accessory(task_id: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    """上传一张 PNG 作为配件（图层编辑器「剥离」的配件也走这里）。"""
    t = _need(task_id)
    root = _edit_root(t)
    name = Path(file.filename or "acc.png").stem
    name = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name).strip("_")[:30] or "acc"
    acc_dir = root / "accessories"
    acc_dir.mkdir(parents=True, exist_ok=True)
    dst = acc_dir / f"{name}.png"
    i = 1
    while dst.exists():                     # 同名不覆盖，追加序号
        dst = acc_dir / f"{name}_{i}.png"
        i += 1
    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    dst.write_bytes(data)
    rel = t.rel_path(dst)
    return {"ok": True, "name": dst.stem, "file": rel, "url": rel}


def _read_accessories(root: Path) -> List[Dict[str, Any]]:
    p = root / "accessories" / "accessories.json"
    if not p.is_file():
        return []
    try:
        items = json.loads(p.read_text(encoding="utf-8"))
        return items if isinstance(items, list) else []
    except Exception:
        return []


@tasks_router.get("/{task_id}/custom-bones")
async def get_custom_bones(task_id: str) -> Dict[str, Any]:
    t = _need(task_id)
    p = _edit_root(t) / "custom_bones.json"
    if not p.is_file():
        return {"bones": []}
    try:
        bones = json.loads(p.read_text(encoding="utf-8"))
        return {"bones": bones if isinstance(bones, list) else []}
    except Exception:
        return {"bones": []}


@tasks_router.post("/{task_id}/custom-bones")
async def put_custom_bones(task_id: str, body: BonesBody) -> Dict[str, Any]:
    t = _need(task_id)
    p = _edit_root(t) / "custom_bones.json"
    p.write_text(json.dumps(body.bones, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return {"ok": True, "count": len(body.bones)}


# ================================================================ 导出接口
def _export_bundle(t) -> Path:
    """预览目录本体就是完整模型包；找不到时报错。"""
    model3 = _read_model3(t)
    return model3.parent


@tasks_router.get("/{task_id}/export")
async def export_model(task_id: str, include_player: bool = Query(True)) -> Dict[str, Any]:
    """打包模型包（含自定义动画）为 zip，可选附带单文件离线播放器。

    返回下载信息；zip 由后台任务在响应送出后删除（放 temp，不留在 workspace）。
    """
    t = _need(task_id)
    bundle = _export_bundle(t)
    model3 = _read_model3(t)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", (t.name or "model")).strip("_")[:30] or "model"
    zip_name = f"{safe}_{stamp}.zip"
    fd, zip_path = tempfile.mkstemp(suffix=".zip", prefix="l2d_export_")
    os.close(fd)
    zip_path = Path(zip_path)

    n = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(bundle.rglob("*")):
            if not p.is_file():
                continue
            zf.write(p, p.relative_to(bundle).as_posix())
            n += 1
        if include_player:
            html = build_player_html(bundle, model3.name,
                                     t.name or "Live2D", config.VENDOR_DIR)
            zf.writestr("player.html", html)
            n += 1

    from urllib.parse import quote

    t.log(f"导出模型包 {zip_name}（{n} 个文件，{zip_path.stat().st_size // 1024}KB）",
          "ok", "preview")
    return {"ok": True, "name": zip_name, "size": zip_path.stat().st_size,
            "files": n,
            "url": f"/api/tasks/{t.id}/export/download/{zip_path.name}"
                   f"?name={quote(zip_name)}"}


@tasks_router.get("/{task_id}/model-info")
async def model_info(task_id: str) -> Dict[str, Any]:
    """给图层/动画编辑器用的模型元数据：cdi3 的可读名 + 贴图列表。

    drawable 的贴图索引只能从运行时拿，这里提供「贴图文件名里的部件名」
    与 cdi3 的 Part/Parameter 对照表，前端用它把 drawable id 翻译成可读名，
    并把贴图 URL 直接给图层缩略图用。
    """
    t = _need(task_id)
    model3 = _read_model3(t)
    meta = json.loads(model3.read_text(encoding="utf-8"))
    fr = meta.get("FileReferences") or {}

    parts, params = [], []
    cdi_rel = fr.get("DisplayInfo")
    if cdi_rel:
        cdi_path = (model3.parent / cdi_rel).resolve()
        try:
            cdi_path.relative_to(model3.parent.resolve())
            cdi = json.loads(cdi_path.read_text(encoding="utf-8"))
            parts = [{"id": p.get("Id", ""), "name": p.get("Name") or p.get("Id", "")}
                     for p in cdi.get("Parts", [])]
            params = [{"id": p.get("Id", ""), "name": p.get("Name") or p.get("Id", ""),
                       "group": p.get("GroupId", "")}
                      for p in cdi.get("Parameters", [])]
        except Exception:
            pass

    textures = []
    for rel in fr.get("Textures") or []:
        p = (model3.parent / rel).resolve()
        try:
            p.relative_to(model3.parent.resolve())
        except ValueError:
            continue
        textures.append({"file": rel, "name": p.stem, "url": t.rel_path(p)})

    return {"model3": t.rel_path(model3), "name": meta.get("Name") or model3.stem,
            "parts": parts, "parameters": params, "textures": textures}


_EXPORT_TOKEN_RE = re.compile(r"^l2d_export_[A-Za-z0-9_]+\.zip$")


@tasks_router.get("/{task_id}/export/download/{token}")
async def export_download(task_id: str, token: str, name: str = Query("")):
    """下载导出的 zip（token 即临时文件名，防路径猜测；name 仅用于下载文件名）。"""
    _need(task_id)
    if not _EXPORT_TOKEN_RE.match(token):
        raise HTTPException(400, "非法下载令牌")
    p = Path(tempfile.gettempdir()) / token
    if not p.is_file():
        raise HTTPException(404, "导出文件不存在或已过期，请重新导出")
    safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name).strip("_")[:60] or "live2d"
    return FileResponse(p, filename=f"{safe}.zip",
                        media_type="application/zip",
                        background=BackgroundTask(lambda: p.unlink(missing_ok=True)))



# ================================================================ 系统接口
@system_router.get("/env")
async def get_env() -> Dict[str, Any]:
    return full_report()


@system_router.get("/config")
async def get_config() -> Dict[str, Any]:
    return config.mask_secrets(config.load())


@system_router.put("/config")
async def put_config(body: ConfigPatch) -> Dict[str, Any]:
    patch = dict(body.patch)
    # 前端回传掩码值 = 未修改，跳过以免把 "******" 存进密钥文件
    if patch.get("api_key") == "******":
        patch.pop("api_key")
    return config.mask_secrets(config.save(patch))


@system_router.post("/env/test-tool")
async def test_tool(body: PickReq) -> Dict[str, Any]:
    p = Path(body.path)
    exists = p.exists()
    kind = "unknown"
    if exists:
        if (p / "inference" / "scripts" / "inference_psd.py").exists():
            kind = "see_through"
        elif (p / "src" / "image2live2d").exists() or (p / "image2live2d").exists():
            kind = "image2live2d"
    return {"exists": exists, "kind": kind, "path": str(p)}


@system_router.post("/env/fetch-vendor")
async def fetch_vendor() -> Dict[str, Any]:
    """把网页预览需要的 JS 依赖下载到本地 vendor/，之后完全离线可用。"""
    results = []
    config.VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        for name, urls in VENDOR_SOURCES.items():
            dst = config.VENDOR_DIR / name
            ok, err = False, ""
            for url in urls:
                try:
                    async with client.stream("GET", url) as r:
                        r.raise_for_status()
                        tmp = dst.with_suffix(".tmp")
                        with tmp.open("wb") as f:
                            async for chunk in r.aiter_bytes():
                                f.write(chunk)
                    if tmp.stat().st_size < 1024:
                        raise ValueError("文件过小，疑似错误页")
                    tmp.replace(dst)
                    ok = True
                    break
                except Exception as e:
                    err = str(e)[:200]
            results.append({"name": name, "ok": ok,
                            "size": dst.stat().st_size if dst.exists() else 0,
                            "error": err})
    return {"results": results, "vendor": full_report()["vendor"]}


@system_router.post("/env/auto-detect-tools")
async def auto_detect_tools() -> Dict[str, Any]:
    """扫描常见位置自动填写工具路径。"""
    found: Dict[str, str] = {}
    roots = [config.TOOLS_DIR, Path.home() / "Downloads",
             Path.home() / "Desktop", Path.cwd().parent]
    seen = set()
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.iterdir()):
            if not p.is_dir() or p.resolve() in seen:
                continue
            seen.add(p.resolve())
            name = p.name.lower()
            if not found.get("see_through_path") and name.startswith("see-through"):
                if (p / "inference" / "scripts" / "inference_psd.py").exists():
                    found["see_through_path"] = str(p)
            if not found.get("image2live2d_path") and name.startswith("image2live2d"):
                if (p / "src" / "image2live2d").exists():
                    found["image2live2d_path"] = str(p)
    if found:
        config.save(found)
    return {"found": found, "config_keys": list(found.keys())}


# ================================================================ 内部
class PickReq(BaseModel):
    path: str


class ConfigPatch(BaseModel):
    patch: Dict[str, Any]


_EXPORT_DIR = Path(tempfile.gettempdir()) / "l2d_exports"


def _need(task_id: str):
    t = manager.get(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return t


def _safe_join(root: Path, rel: str) -> Path:
    """任务目录内的安全路径解析。用 relative_to 做包含性校验，
    startswith 前缀比较会放过「另一个目录名恰好是本目录前缀」的情况。"""
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(403, "越界访问")
    return target


def _unzip_into(data: bytes, dest: Path) -> List[str]:
    """把上传的 zip 解到 dest，逐条校验解出的路径没越界（zip-slip）。

    返回解出的文件名列表，调用方据此判断这次上传里有没有目标产物 ——
    不能查解包后的目录：里面可能躺着上一次上传留下的文件。
    """
    import io
    import zipfile

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(400, "不是有效的 zip 文件（可能上传中断或文件损坏）")

    root = dest.resolve()
    names: List[str] = []
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            target = (dest / info.filename).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                raise HTTPException(400, f"zip 内含越界路径：{info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
            names.append(info.filename)
    return names


async def _start(t, from_stage: Optional[str]) -> int:
    """提交到全局队列，返回排队位置（0 = 已开始）。"""
    try:
        return jobs.submit(t, from_stage)
    except JobBusyError as e:
        raise HTTPException(409, str(e))
