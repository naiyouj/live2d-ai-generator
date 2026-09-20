# Live2D AI Generator v2

English | [简体中文](README.md)

A fully local web app that turns **AI image generation → one image → an animatable Live2D model**. Everything runs on your own machine.

```
Step 1 Image Gen  →  Step 2 Preprocess  →  Step 3 Layering  →  Step 4 Rigging  →  Step 5 Preview/Export
   character PNG       cutout & crop        20+ RGBA layers     mesh/physics/motion   .moc3 model pack
```

## Features

- **Fully local pipeline**: image gen → layering → rigging → export, all on your machine. No images leave your computer.
- **Visual pipeline console**: browser UI (`http://127.0.0.1:7800`) with live five-step progress.
- **Global task queue**: only one pipeline runs at a time, so even an 8GB GPU won't get into memory fights.
- **Manual takeover at every stage**: upload your own artifacts (character PNG / PSD / `.moc3`) to skip any step.
- **API key isolation**: keys live in `data/secrets.json`, excluded from backups by default.
- **Resumable**: finished steps are skipped automatically; re-run from any step.

v2 is a full rewrite: code reorganized into the `server/` package, a global task queue (one pipeline at a time so an 8GB GPU doesn't fight itself), typed configuration, and **API keys moved from config.json into `data/secrets.json`** (excluded from backup archives). External behavior matches v1; old task directories stay compatible.

---

## Quick Start

**Double-click `启动.bat`** (Start) — it opens `http://127.0.0.1:7800` in your browser.

| Script | Purpose |
|---|---|
| **`启动.bat`** (Start) | day-to-day server launch |
| `安装环境.bat` (Install env) | install/repair Python dependencies (only needed once) |
| `下载外部工具.bat` (Fetch tools) | download the see-through / image2live2d repos and apply local patches automatically, plus the web preview JS libs (~150MB; **run this first on a fresh clone from GitHub**) |
| `下载分层模型.bat` (Fetch models) | pre-download the three models for step 3 (~12GB, once; skips finished files) |
| `备份打包.bat` (Backup zip) | zip the whole project, **excluding API keys** (`--no-venv` makes it much smaller) |

All scripts use the project-local `.venv` and never touch the system Python.

### Environment (this dev machine)

- Python: `C:\Python313` (3.13.9, user-level install); `.venv`'s `pyvenv.cfg` points at it.
- GPU: RTX 2070 8GB, torch 2.8.0+cu126, CUDA available.

### Crash / error triage

`启动.bat` pauses on error so you can read it. If you see `venv not found`:

```bat
python -m venv .venv
.venv\Scripts\python.exe setup_env.py
```

> **Editing the .bat files**: they must stay **pure ASCII + CRLF** (write them in binary from any script). UTF-8 without BOM garbles them, LF makes adjacent statements stick together — VS Code's default UTF-8 save is a classic trap.

### Port conflicts

```
.venv\Scripts\python.exe run.py --port 8080
.venv\Scripts\python.exe run.py --host 0.0.0.0 --port 8080   # LAN-accessible
```

---

## First Run (new machine)

> Prerequisites: install [git or GitHub Desktop](https://github.com/) to clone the code,
> and Python 3.13 (`python -m venv .venv` needs it). Large files are not in the
> repo — the steps below fetch everything automatically.

1. **`安装环境.bat`** (once): detects your GPU driver, picks the matching CUDA PyTorch build, installs see-through inference deps, image2live2d, rembg, web console deps, and writes `data/config.json`. Downloads 3–5GB; safe to re-run (finished parts are skipped). Check the report for `torch 2.8.0+cu126` / `cuda True`.
2. **`下载外部工具.bat`**: downloads see-through / image2live2d into `tools/` at pinned commits, overlays the local patches from `patches/`, and fetches Cubism Core / PixiJS / pixi-live2d-display into `server/web/vendor/`. No git required.
3. **`下载分层模型.bat`** (needed for step 3): pre-downloads the three HF models, ~12GB.
4. **Settings → Image gen**: configure your generation backend:
   - Online/local API: OpenAI-compatible endpoint (`https://xxx/v1`) + key + model name
   - ComfyUI: address + workflow in API format (prompts and seed are auto-replaced)
   - **Upload a local image**: simplest, skips image generation entirely

   Settings live in `data/config.json` (keys in `data/secrets.json`); neither is
   tracked by git. To bootstrap quickly, copy `data/config.example.json`,
   rename it, then fine-tune in the web UI.

The two external tool repos are **not tracked by git** (large + upstream respect).
`下载外部工具.bat` fetches them at the pinned commits recorded in
`patches/*/HEAD.txt` and applies the patches:

| Tool | Location | Pipeline step |
|---|---|---|
| see-through | `tools\see-through` | Step 3 layering |
| image2live2d | `tools\image2live2d` | Step 4 rigging |

## Hard Requirements for Image Generation

This is the **only stage that needs human judgment**; the other four steps are automatic:

- **A-pose** — arms naturally down, slightly away from the torso (dynamic poses make head/hair meshes detach)
- **Plain solid background** — busy backgrounds ruin the layering
- **Full body + front view + single character** — half body, side views, multiple characters all fail

The default "positive suffix" and "negative prompt" already encode these three rules — don't remove them.

## VRAM Tiers

Step 3 (layering) is the only VRAM bottleneck. The app recommends settings from your VRAM; override manually if you like:

| VRAM | Precision | Resolution | group_offload |
|---|---|---|---|
| ≥16GB | bf16 | 1280 | off |
| 11–15GB | bf16 | 1024 | on |
| 8–11GB | NF4 quantized | 1024 | forced off (conflicts with bnb 4-bit) |
| No NVIDIA GPU | — | — | run layering on a cloud GPU, then upload the PSD to take over step 4 |

An 8GB card takes **about 1 hour** for 1024 layering; 768 roughly halves that. The task queue runs one pipeline at a time; extra tasks queue up automatically.

## Manual Takeover at Any Step

Click any pipeline step, then **「上传接管」(Upload takeover)** at the top right:

- Step 1 — upload your own character PNG
- Step 3 — upload a `layers.psd` produced elsewhere
- Step 4 — upload an existing `.moc3`, or zip an entire model directory (`.moc3` + `model3.json` + `textures/` with textures). Preview needs `model3.json` to find the model and the textures to render — a bare `.moc3` can't be driven

"Re-run from this step" only re-runs the second half; earlier artifacts are kept. Clicking it on step 1 means a genuinely new image (in gen modes; in upload mode it reuses your uploaded image).

## Editing Workbench (Animation / Layers tabs)

After step 5 completes, below the preview is a **tabbed editing workbench**: the "Animation" and "Layers" sub-pages switch in place — no more endless scrolling between stacked panels — and the canvas stays visible. Drag bone handles right on the Animation tab.

### Animation (Blender-style bones + dope sheet)

- **Bone handles**: moc3 files have no skeleton, so this panel provides 9 draggable handles grouped by parameter (head/eyes/brows/mouth/body/both arms/front & back hair), anchored to the centroid of the corresponding part's mesh. Dragging writes parameters (X drag → horizontal channel, Y drag → vertical channel) and updates the model in real time.
- **Custom bones**: "＋骨骼" (＋Bone) creates handles for parts the built-ins don't cover (skirts, ribbons, tails…) — pick any mesh as anchor, bind any parameter channels (axis + sensitivity). Definitions persist in the model pack as `custom_bones.json`; edit/delete from the bone row.
- **Accessories**: "＋图片" (＋Image) uploads a PNG (or lasso-peel one from the Layers tab) and binds it to any bone: follow weight (1 = glued to the bone, 0 = pinned to canvas center), scale, rotation, offset, front/back layering — all editable in the list; drag accessories on the canvas to adjust offset. Data lives in `accessories/accessories.json`; the exported player.html embeds accessories and replicates the follow logic.
- **Keyframing**: pose a bone then press **K** (or "K 打帧") to key the selected bone; **K! 全部** keys every touched bone; tick **auto-key** to key on every drag end. Shortcuts: `Space` play/pause, `K` key, `Delete` remove frames at the playhead.
- **Dope sheet**: one row per bone, diamonds = keyframes. Drag to retime, click to cycle easing (linear/smooth/stepped), right-click to delete; drag the ruler to move the playhead.
- **Save motion**: name it, hit "保存动作" — it writes a standard `motion3.json` into the model pack and registers it under the `Custom` group in `model3.json` (Cubism Editor recognizes it too). Replay any time from the motion list; deletable.
- **Export model pack**: one click packs `moc3 + textures + model3.json + all motions + accessories + custom bones`, plus a single-file `player.html` (model and accessories embedded as data URLs) — double-click it in any browser to drive the model and motions, no server needed.

### Idle motions automatically lose the Z axis

Auto-generated idle motions carry `ParamAngleZ / ParamBodyAngleZ` (in-plane rotation) curves, which make AI-generated meshes twist weirdly. They're stripped automatically when the preview pack is built (`server/motutil.py`), and the frontend re-applies the strip idempotently before loading — idle motions keep only X/Y sway.

## Layer Manager (with image editing)

After step 5, layers are shown as cards **grouped by part**: group headers show a texture thumbnail, the human-readable part name from cdi3 (Hair Back / Clothing…) and the mesh count; mesh rows carry UV-cropped thumbnails, with ▲▼ nudge and drag-to-reorder. "隐藏" (Hide) turns off a whole part's opacity (the Cubism core has no per-mesh visibility API). "还原" (Reset) restores factory order.

The **"✎ 图" (edit image)** button on a group header opens an image editor to fix what the AI didn't cut cleanly:

- **Eraser / lasso erase**: scrub fringes and leftover background to transparent (undoable; saving writes back to the texture);
- **Lasso peel to accessory**: circle an accessory or prop and it's cut into a standalone PNG and added to the accessories list — bind it to a bone in the Animation tab to make it move;
- **Replace whole image**: swap the entire texture with a local file.
  The model hot-reloads after saving.

## Directory Layout

```
server/          backend (FastAPI) + frontend pages
  config.py      typed config; keys in data/secrets.json, separate from config.json
  tasks.py       task state machine + global execution queue (GPU serialization)
  runner.py      subprocess executor (\r/\n dual line splitting + progress throttling)
  progress.py    see-through output → UI progress mapping
  stages.py      the five stage implementations
  pipeline.py    orchestration (skip finished / re-run from a stage)
  envcheck.py    environment self-check (incl. see-through Marigold batch patch detection)
  api.py         all HTTP/WS endpoints (motions/textures/accessories/custom bones/export)
  motutil.py     strip Z-axis curves from idle motions (shared by packing & manual fix)
  player.py      single-file offline player generator (incl. accessory following)
  web/           index.html / app.css / app.js / vendor (preview libs, git-ignored)
patches/         local patch snapshots for the external tools (whole-file overlays +
                 changes.diff + HEAD.txt pinned commits); applied by the fetch-tools script
tools/           our own scripts (fetch_tools / download_models / make_backup) +
                 two external repos (git-ignored, fetched by script)
workspace/       task artifacts, one directory per task, subdirectories per stage (git-ignored)
data/            config.json (local settings, git-ignored) + secrets.json (API keys,
                 git-ignored) + config.example.json (committed template)
```

### What's in the git repo, and what isn't

- **In the repo**: all first-party code (`server/`, `tools/*.py`, root-level py + bat files), the `patches/` snapshots, and the `data/config.example.json` template.
- **Not in the repo** (rebuilt/downloaded automatically): `.venv` (install-env script), `tools/see-through` and `tools/image2live2d` (fetch-tools script), `server/web/vendor` (fetch-tools script or the self-check button), `workspace/` (task artifacts), `logs/`, `data/config.json` (local settings), `data/secrets.json` (**API keys never enter git**).

## API

OpenAPI docs at `http://127.0.0.1:7800/docs`.

Cancel and delete task endpoints (`POST /api/tasks/{id}/cancel`, `DELETE /api/tasks/{id}`) currently have no UI buttons — call them from `/docs`. Cancel also `taskkill /T`s the running subprocess — otherwise the VRAM-holding inference process survives and the next queued task is guaranteed to OOM.

## Tests

```
.venv\Scripts\python.exe smoke_test.py            # API smoke test (doesn't touch real config)
.venv\Scripts\python.exe test_progress_mapping.py # progress mapping replay
```

## Notes & Caveats

- `.moc3` is Live2D's closed binary format; generated models rely on community reverse engineering. Fine for personal use, but **run the model through Cubism Editor and re-export before any commercial use**.
- `tools/see-through`'s `inference_psd_quantized.py` carries a local patch (Marigold batched inference, `L2D_DEPTH_BATCH`). The patch lives as a whole-file snapshot in `patches/see-through/overlay/`, applied automatically by the fetch-tools script. **If you update the repo, re-export the patch** (re-snapshot and update the commit in `HEAD.txt`); the environment self-check verifies the patch is in place.
- `tools/image2live2d`'s `src/image2live2d/__main__.py` carries a local patch: the CLI's `--live2d` only writes the JSON model files (model3/physics3/motion3/cdi3) by default, not the `.moc3` binary. The patch injects `native_moc_writer` (generates `.moc3` from scratch) so step 4 gets a `.moc3` artifact. The snapshot (including the two added files `_head.bin` and `tests/test_neck_zorder.py`) lives in `patches/image2live2d/`, applied automatically by the fetch-tools script. **If you update the repo, re-export the patch** (add `moc_writer=native_moc_writer` at the `Live2DEmitter(...)` call and import `from .backends.live2d.moc3_emit import native_moc_writer`).
- API keys are stored in plain text in `data/secrets.json` (git-ignored). Use `备份打包.bat` (auto-excludes them) when packaging/sharing — don't zip the whole directory by hand.
- [see-through](https://github.com/shitagaki-lab/see-through) and [image2live2d](https://github.com/Wzhang3912/image2live2d) are Apache-2.0 open-source projects. The overlay snapshots in `patches/` are just the minimal changes this project needs; copyright stays with the respective upstream authors. See `changes.diff` alongside each snapshot for the exact diffs.
