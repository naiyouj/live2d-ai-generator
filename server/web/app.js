/* Live2D AI 生成器 v2 —— 前端控制台 */
(() => {
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const api = async (u, o = {}) => {
  const r = await fetch(u, {
    headers: { "Content-Type": "application/json", ...(o.headers || {}) },
    ...o,
  });
  if (!r.ok) throw new Error((await r.text()).slice(0, 300));
  return r.status === 204 ? null : r.json();
};

const STATUS_TEXT = {
  idle: "待命", queued: "排队中", running: "运行中",
  done: "已完成", error: "失败", cancelled: "已取消",
  pending: "等待", skipped: "跳过",
};

const state = {
  cfg: {}, env: {}, tasks: [], stages: [],
  task: null, current: null, ws: null, sel: "generate", logFilter: "all",
  uiTab: "anim",      // 工作台子页：anim | layers
};

/* ---------------- toast ---------------- */
let toastTimer = null;
function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast " + kind; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 4200);
}

/* ---------------- 环境 / 配置 ---------------- */
async function loadEnv() {
  try { state.env = await api("/api/env"); } catch (e) { return; }
  renderChips();
  if (!$("#modalEnv").hidden) renderEnvModal();
}

function renderChips() {
  const e = state.env, g = e.gpu || {};
  const chip = (cls, html) => `<span class="chip"><i class="dot ${cls}"></i>${html}</span>`;
  $("#envChips").innerHTML = [
    chip(g.available ? "ok" : "warn",
      g.available ? `GPU <b>${esc(g.name)}</b> ${g.vram_gb}GB` : "CPU 模式"),
    chip(e.tools?.see_through?.ok ? "ok" : "err", "see-through"),
    chip(e.tools?.image2live2d?.ok ? "ok" : "err", "image2live2d"),
    chip(e.deps?.rembg ? "ok" : "warn", "rembg"),
    chip(e.vendor?.ok ? "ok" : "warn", "预览依赖"),
  ].join("");
}

async function loadConfig() {
  try { state.cfg = await api("/api/config"); } catch (e) { toast("读取配置失败", "err"); }
}

/* ---------------- 任务列表 ---------------- */
async function loadTasks() {
  try {
    const [list, stages] = await Promise.all([api("/api/tasks"), api("/api/tasks/stages")]);
    state.tasks = list; state.stages = stages;
  } catch (e) { return; }
  renderTaskList(); renderPipeline();
}

function renderTaskList() {
  const box = $("#taskList");
  if (!state.tasks.length) {
    box.innerHTML = `<div class="taskEmpty">还没有任务</div>`;
    return;
  }
  box.innerHTML = state.tasks.map(t => {
    const done = Object.values(t.stages).filter(s => s.status === "done").length;
    const st = STATUS_TEXT[t.status] || t.status;
    return `<div class="taskItem ${t.id === state.current ? "active" : ""}" data-id="${t.id}">
      <div class="tn">${esc(t.name)}</div>
      <div class="tm"><span>${done}/5 步</span><span>${esc(st)}</span></div>
    </div>`;
  }).join("");
  $$(".taskItem").forEach(el => el.onclick = () => openTask(el.dataset.id));
}

/* ---------------- 流水线 ---------------- */
function renderPipeline() {
  const t = state.task;
  $("#pipeline").innerHTML = state.stages.map((s, i) => {
    const st = t?.stages?.[s.id] || { status: "pending", progress: 0, message: "" };
    const badge = STATUS_TEXT[st.status] || st.status;
    return `<div class="step ${t && s.id === state.sel ? "active" : ""}"
        data-s="${st.status}" data-sid="${s.id}">
      <div class="badge">${esc(badge)}</div>
      <div class="idx">${i + 1}</div>
      <div class="nm">${esc(s.name)}</div>
      <div class="ds">${esc(s.desc)}</div>
      <div class="msg" title="${esc(st.message || "")}">${esc(st.message || "尚未开始")}</div>
      <div class="bar"><i style="width:${st.progress || 0}%"></i></div>
    </div>`;
  }).join("");
  $$(".step").forEach(el => el.onclick = () => {
    state.sel = el.dataset.sid; renderPipeline(); renderDetail();
  });
}

/* ---------------- 详情 ---------------- */
const fileUrl = (p) => `/api/tasks/${state.task.id}/files/${p}`;

function renderDetail() {
  const t = state.task, sid = state.sel, box = $("#detail");
  const st = t?.stages?.[sid] || {};
  const def = state.stages.find(s => s.id === sid) || {};
  $("#detailTitle").textContent = `${def.name || ""} · 产物`;
  // 取消只对在跑/排队中的任务有意义；删除随时可用（带确认）
  $("#btnCancel").disabled = !t || !["running", "queued"].includes(t.status);
  $("#btnDelete").disabled = !t;
  if (!t) {
    box.innerHTML = `<div class="empty">先选择或创建一个任务</div>`;
    return;
  }
  if (st.status === "error") {
    box.innerHTML = `<div class="errBox"><b>失败：</b>${esc(st.message)}</div>` + filesHtml(st);
    return;
  }
  if (!st.outputs?.length) {
    box.innerHTML = `<div class="empty">${esc(st.message || "暂无产物")}</div>`;
    return;
  }
  box.innerHTML = filesHtml(st);
}

function filesHtml(st) {
  const imgs = (st.outputs || []).filter(f => f.is_image);
  const rest = (st.outputs || []).filter(f => !f.is_image);
  let html = "";
  if (state.sel === "decompose" && imgs.length) {
    html += `<div class="thumbGrid">` + imgs.slice(0, 80).map(f =>
      `<div class="thumb"><img src="${fileUrl(f.path)}" loading="lazy">
        <div class="cap">${esc(f.name)}</div></div>`).join("") + `</div>`;
    if (imgs.length > 80) html += `<div class="empty">仅显示前 80 个图层…</div>`;
  } else if (imgs.length) {
    html += imgs.map(f => `<img src="${fileUrl(f.path)}"
      style="width:100%;max-height:300px;object-fit:contain;border-radius:8px;margin-bottom:8px">`).join("");
  }
  if (rest.length) {
    html += rest.slice(0, 40).map(f => `<div class="fileRow">
      <span>${esc(f.name)}</span>
      <span>${(f.size / 1024).toFixed(1)}KB
        <a href="${fileUrl(f.path)}" target="_blank">下载</a></span></div>`).join("");
  }
  return html;
}

/* ---------------- 日志 ---------------- */
function renderLogs() {
  const box = $("#logBox"), t = state.task;
  if (!t) { box.innerHTML = ""; return; }
  let lines = t.logs || [];
  if (state.logFilter === "error") lines = lines.filter(l => l.level === "error" || l.level === "warn");
  if (state.logFilter === "cmd") lines = lines.filter(l => l.level === "cmd" || l.level === "error");
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
  box.innerHTML = lines.map(l => {
    const ts = new Date(l.t * 1000).toLocaleTimeString("zh-CN", { hour12: false });
    return `<div class="logLine"><span class="ts">${ts}</span>
      <span class="lv lv-${l.level}">${l.level}</span>
      <span class="logBody">${esc(l.msg)}</span></div>`;
  }).join("") || `<div class="empty">暂无日志</div>`;
  if (atBottom) box.scrollTop = box.scrollHeight;
}

/* ---------------- 任务打开 / WS ---------------- */
async function openTask(id) {
  state.current = id;
  try { state.task = await api(`/api/tasks/${id}`); }
  catch (e) { toast("读取任务失败", "err"); return; }
  renderTaskList(); renderPipeline(); renderDetail(); renderLogs();
  connectWs(id);
  maybeLoadModel();
}

function connectWs(id) {
  if (state.ws) { try { state.ws.close(); } catch (e) {} }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/api/tasks/${id}/ws`);
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "snapshot") state.task = m.data;
    else if (m.type === "stage") {
      state.task.stages[m.data.id] = { ...state.task.stages[m.data.id], ...m.data };
      if (m.data.status === "running") state.task.status = "running";
    } else if (m.type === "log") state.task.logs.push(m.data);
    else if (m.type === "done") { loadTasks(); openTask(id); return; }
    renderPipeline(); renderDetail(); renderLogs(); maybeLoadModel();
  };
  ws.onclose = () => { if (state.ws === ws) state.ws = null; };
  state.ws = ws;
}

/* ---------------- 创建任务 ---------------- */
async function createTask() {
  const genMode = $("#fGenMode").value;
  const file = $("#fUpload").files?.[0];
  const body = {
    name: $("#fName").value.trim(),
    prompt: $("#fPrompt").value.trim(),
    params: {
      gen_mode: genMode,
      preprocess_method: $("#fPre").value,
      decomp_precision: $("#fPrecision").value,
      decomp_resolution: +$("#fRes").value,
      decomp_group_offload: $("#fOffload").checked,
    },
    run: false,
  };
  if (genMode !== "upload" && !body.prompt) { toast("请填写生图提示词", "err"); return; }
  if (genMode === "upload" && !file) { toast("请选择一张立绘", "err"); return; }

  try {
    const r = await api("/api/tasks", { method: "POST", body: JSON.stringify(body) });
    if (genMode === "upload" && file) {
      const fd = new FormData(); fd.append("file", file);
      const up = await fetch(`/api/tasks/${r.id}/input/generate`, { method: "POST", body: fd });
      if (!up.ok) throw new Error((await up.text()).slice(0, 200));
    }
    const rr = await api(`/api/tasks/${r.id}/run`, { method: "POST", body: "{}" });
    toast(rr.queue > 0 ? `任务已加入队列（前面还有 ${rr.queue} 个）` : "任务已启动", "ok");
    state.sel = "generate";
    $("#fName").value = ""; $("#fPrompt").value = ""; $("#fUpload").value = "";
    await loadTasks(); await openTask(r.id);
  } catch (e) { toast("创建失败：" + e.message, "err"); }
}

/* ---------------- 模型预览 ---------------- */
let pixiApp = null, l2dModel = null, loadedModelUrl = "";
let vendorPromise = null, l2dLoading = false;
let modelInfo = null;              // /model-info：cdi3 可读名 + 贴图/部件对照

// vendor 文件更新后递增此版本号，避免浏览器沿用旧缓存
const VENDOR_VER = 3;

// 手动姿态覆盖：滑杆 / 骨骼拖拽写的参数值每帧在 beforeModelUpdate 里生效。
// 不走这里的话，待机动画每帧都会把滑杆值打回去
const poseOverride = new Map();

// 动画编辑器状态（Blender 式：骨骼 = 参数组手柄，关键帧按骨骼整体记录）
const animState = {
  open: false, playing: false, t: 0, duration: 3, loop: true, autoKey: false,
  bones: [],        // {id,name,channels:[{ids,axis,sens,label}],anchorIdx,show,keys:[{t,mode,vals}]}
  selected: null,   // 选中骨骼 id
  params: [],       // 模型参数表 [{id,name,group,min,max,def}]
  motions: [],      // 已登记动作 [{group,name,gi,editable}]
  customDefs: [],   // 自定义骨骼定义（持久化在模型包 custom_bones.json）
};

// 配件（PNG 跟随骨骼，权重可调；持久化在模型包 accessories/）
const accState = { list: [], sprites: [], sel: null };

function ensureVendor() {
  // 5 秒轮询 / WS 推送会并发触发加载，这里用单例 Promise 防止重复插 <script>
  if (vendorPromise) return vendorPromise;
  vendorPromise = (async () => {
    const files = ["pixi.min.js", "live2dcubismcore.min.js", "pixi-live2d-display.min.js"];
    for (const f of files) {
      if (document.querySelector(`script[data-v="${f}"]`)) continue;
      await new Promise((res, rej) => {
        const s = document.createElement("script");
        s.src = `/vendor/${f}?v=${VENDOR_VER}`; s.dataset.v = f;
        s.onload = res; s.onerror = () => rej(new Error(f));
        document.head.appendChild(s);
      });
    }
  })();
  // 加载失败允许下次重试
  vendorPromise.catch(() => { vendorPromise = null; });
  return vendorPromise;
}

async function maybeLoadModel() {
  const st = state.task?.stages?.preview;
  if (!st || st.status !== "done" || !st.artifacts?.model_json) return;
  const url = fileUrl(st.artifacts.model_json);
  // l2dLoading 挡住轮询/WS 在异步加载窗口期内的重复触发，
  // 否则两次 loadModel 并发会互踩（destroy 掉对方正在用的 app/canvas）
  if (url === loadedModelUrl || l2dLoading) return;
  l2dLoading = true;
  $("#previewHint").hidden = true;
  try {
    modelInfo = await api(`/api/tasks/${state.task.id}/model-info`).catch(() => null);
    // 自动生成的待机动作带 Z 轴（面内旋转）曲线，2D 网格转起来会扭曲，
    // 加载前先剔除（服务端幂等，改完的文件下次加载直接干净）
    api(`/api/tasks/${state.task.id}/fix-idle`, { method: "POST" }).catch(() => null);
    await ensureVendor();
    if (!window.PIXI?.Application) throw new Error("pixi.js 未加载");
    // 注意：必须校验 Live2DModel 本身。vendor 脚本初始化失败时
    // PIXI.live2d 可能只是个空对象，不能只判 PIXI.live2d
    if (!window.PIXI?.live2d?.Live2DModel) throw new Error("pixi-live2d-display 未加载");
    await loadModel(url);
  } catch (e) {
    $("#previewHint").textContent =
      /pixi|cubism|display/i.test(e.message)
        ? "预览依赖缺失，请在「环境自检」里点「下载网页预览依赖」"
        : "模型加载失败：" + e.message;
    $("#previewHint").hidden = false;
  } finally {
    l2dLoading = false;
  }
}

async function loadModel(url, force = false) {
  if (url === loadedModelUrl && !force) return;
  const canvas = $("#l2d"), wrap = canvas && canvas.parentElement;
  if (!canvas) return;
  // 复用同一个 Application / canvas：destroy(true) 会把 canvas 从 DOM 摘掉，
  // 摘掉后再挂回去会拿不到新的 WebGL 上下文
  if (l2dModel) {
    pixiApp.stage.removeChild(l2dModel);
    l2dModel.destroy();
    l2dModel = null;
  }
  if (!pixiApp) {
    pixiApp = new PIXI.Application({
      view: canvas, backgroundAlpha: 0, antialias: true,
      resizeTo: wrap, resolution: window.devicePixelRatio || 1,
    });
    pixiApp.ticker.add(fit);
    pixiApp.ticker.add(animTick);
    pixiApp.ticker.add(updateAccessories);
  }
  l2dModel = await PIXI.live2d.Live2DModel.from(url, { autoInteract: false });
  window.__l2d = l2dModel;
  poseOverride.clear();
  setPlaying(false);
  animState.t = 0;
  initLayerControl(l2dModel);
  hookBeforeUpdate(l2dModel);
  loadParams(l2dModel);
  const prevKeys = new Map(animState.bones.map(b => [b.id, b.keys]));
  await loadCustomBones();
  buildBones(l2dModel);
  // 重载模型（保存动作/换贴图后）不清空编辑进度：同 id 骨骼的关键帧带过去
  for (const b of animState.bones) {
    if (prevKeys.has(b.id)) b.keys = prevKeys.get(b.id);
  }
  ensureBoneOverlay();
  await loadAccessories();
  l2dModel.anchor.set(0.5, 0.05);
  pixiApp.stage.addChild(l2dModel);
  fit();
  loadedModelUrl = url;
  $("#ctrlRow").hidden = false;
  $("#btnAnim").hidden = false;
  $("#btnExport").hidden = false;
  $("#workbench").hidden = false;
  setTab(state.uiTab || "anim");
  await refreshMotions();
}

/* ---------------- 图层顺序（分组缩略图版） ----------------
 * Cubism 核心每帧 update 会重算原生 renderOrders，直接改写会被打回；
 * 但渲染器每帧都通过 getDrawableRenderOrders() 读取排序，所以在模型实例上
 * 遮蔽该方法、返回自持数组即可运行时改层级。
 *
 * 面板按「贴图」分组：生成模型的贴图与 PSD 部件一一对应（hair_back、face…
 * 文件名自带语义），缩略图直接从贴图里按 drawable 的 UV 裁出来。
 * 眼睛按钮控制的是「部件」不透明度 —— 核心没有单 drawable 的显隐接口。 */
let layerOrderArr = null;   // 遮蔽数组：drawableIdx -> renderOrder（0 = 最底层）
let layerNativeArr = null;  // 出厂顺序快照，供「还原」
let layerIds = [];          // drawableIdx -> 部件 mesh id
let layerTex = [];          // drawableIdx -> 贴图序号（用于分组/命名/缩略图）
let layerThumb = [];        // drawableIdx -> dataURL 缩略图（可能为 null）
const texHidden = new Map();   // 贴图序号 -> 是否整组隐藏

const normName = (s) => String(s || "").toLowerCase().replace(/[^a-z]/g, "");

function texInfo(ti) {
  const tex = modelInfo?.textures?.[ti];
  const raw = tex ? tex.name : ("tex" + ti);
  const url = tex ? fileUrl(tex.url) : "";
  // 贴图文件名 ↔ cdi3 部件名对上就用官方可读名（00_hair_back ↔ 000_tex_00_hair_back）
  const parts = modelInfo?.parts || [];
  let part = null;
  for (const p of parts) {
    const nid = normName(p.id);
    if (nid.length > 3 && normName(raw).includes(nid)) { part = p; break; }
  }
  const fallback = raw.replace(/^[0-9_]*tex[t_]*[0-9_]*/i, "").replace(/_/g, " ") || raw;
  return { name: part ? part.name : fallback, url, partId: part ? part.id : null };
}

function texIndexOf(core, i, n) {
  // getDrawableTextureIndices 有两种签名：按索引返回单个数组 / 无参返回全体
  try {
    const r = core.getDrawableTextureIndices(i);
    if (typeof r === "number") return r;
    if (r && r.length) return r.length === n ? r[i] : r[0];
  } catch (e) {}
  return 0;
}

function buildLayerMeta(model) {
  const im = model.internalModel, core = im.coreModel;
  const n = core.getDrawableCount();
  // 贴图数组挂在 Live2DModel.textures 上（internalModel 没有）。缩略图
  // 直接拿每张贴图底下的源图（HTMLImageElement）裁 —— 本项目的 PIXI
  // 构建不带 extract 插件，pixiApp.renderer.plugins.extract 是 undefined
  const atlas = [];
  for (const tex of (model.textures || [])) {
    const src = tex?.baseTexture?.resource?.source;
    atlas.push(src && src.width ? src : null);
  }
  const flipY = !!im.textureFlipY;   // UV 与贴图上下颠倒的模型要翻着裁
  layerTex = []; layerThumb = [];
  for (let i = 0; i < n; i++) {
    const ti = texIndexOf(core, i, n);
    layerTex[i] = ti;
    layerThumb[i] = cropThumb(atlas[ti], core, i, flipY);
  }
}

function cropThumb(atlas, core, i, flipY) {
  // atlas 是贴图源图（HTMLImageElement / HTMLCanvasElement），drawImage 都认
  if (!atlas) return null;
  try {
    const uv = core.getDrawableVertexUvs(i);     // [u,v, u,v, ...]
    if (!uv || uv.length < 4) return null;
    let u0 = 1, v0 = 1, u1 = 0, v1 = 0;
    for (let k = 0; k < uv.length; k += 2) {
      u0 = Math.min(u0, uv[k]); u1 = Math.max(u1, uv[k]);
      v0 = Math.min(v0, uv[k + 1]); v1 = Math.max(v1, uv[k + 1]);
    }
    if (flipY) { const t = 1 - v0; v0 = 1 - v1; v1 = t; }
    if (u1 - u0 < 1e-4 || v1 - v0 < 1e-4) return null;
    const W = atlas.width, H = atlas.height;
    const padU = (u1 - u0) * 0.06, padV = (v1 - v0) * 0.06;
    const sx = Math.max(0, (u0 - padU) * W), sy = Math.max(0, (v0 - padV) * H);
    const sw = Math.min(W - sx, (u1 - u0 + padU * 2) * W);
    const sh = Math.min(H - sy, (v1 - v0 + padV * 2) * H);
    if (sw < 1 || sh < 1) return null;
    const S = 44, sc = Math.min(S / sw, S / sh);
    const c = document.createElement("canvas");
    c.width = S; c.height = S;
    c.getContext("2d").drawImage(atlas, sx, sy, sw, sh,
      (S - sw * sc) / 2, (S - sh * sc) / 2, sw * sc, sh * sc);
    return c.toDataURL();
  } catch (e) { return null; }
}

function initLayerControl(model) {
  try {
    const core = model.internalModel.coreModel;
    const n = core.getDrawableCount();
    layerNativeArr = core.getDrawableRenderOrders().slice();
    layerOrderArr = layerNativeArr.slice();
    layerIds = Array.from({ length: n }, (_, i) => core.getDrawableId(i));
    buildLayerMeta(model);
    texHidden.clear();
    autoFixNeckOrder();
    core.getDrawableRenderOrders = () => layerOrderArr;
    renderLayerList();
    $("#workbench").hidden = false;
  } catch (e) { /* 图层元数据失败不挡动画编辑 */ }
}

function autoFixNeckOrder() {
  const neck = layerIds.findIndex(id => /neck/i.test(id));
  const anchor = layerIds.findIndex(id => /ear_l|face/i.test(id));
  if (neck < 0 || anchor < 0 || neck < anchor) return; // 顺序正常或部件名不符
  moveLayerTo(layerOrderArr, neck, anchor); // 把脖子挪到耳朵/脸之前
}

// 底→顶序列里把 from 移到 before 之前，重排为 0..n-1 的合法排列
function moveLayerTo(arr, fromIdx, beforeIdx) {
  const n = arr.length;
  const seq = Array.from({ length: n }, (_, i) => i).sort((a, b) => arr[a] - arr[b]);
  seq.splice(seq.indexOf(fromIdx), 1);
  seq.splice(seq.indexOf(beforeIdx), 0, fromIdx);
  seq.forEach((di, order) => { arr[di] = order; });
}

// 当前「底 → 顶」的 drawable 序列（重排操作都在这上面做）
function seqIndices() {
  return Array.from({ length: layerOrderArr.length }, (_, i) => i)
    .sort((a, b) => layerOrderArr[a] - layerOrderArr[b]);
}
function applySeq(seq) {
  seq.forEach((di, k) => { layerOrderArr[di] = k; });
  renderLayerList();
}
function shiftLayer(idx, dir) { // dir +1 = 提前一层（更靠前）
  const seq = seqIndices();
  const pos = seq.indexOf(idx), t = pos + dir;
  if (t < 0 || t >= seq.length) return;
  [seq[pos], seq[t]] = [seq[t], seq[pos]];
  applySeq(seq);
}
function moveTo(idx, targetIdx) {   // 拖拽：落到目标所在的层级
  const seq = seqIndices();
  seq.splice(seq.indexOf(idx), 1);
  seq.splice(seq.indexOf(targetIdx), 0, idx);
  applySeq(seq);
}

function toggleTexGroup(ti) {
  if (!l2dModel) return;
  const core = l2dModel.internalModel.coreModel;
  const info = texInfo(ti);
  let pi = -1;
  try { if (info.partId) pi = core.getPartIndex(info.partId); } catch (e) {}
  if (pi == null || pi < 0) {
    toast("这张贴图找不到对应部件，无法整组隐藏", "err");
    return;
  }
  const hide = !texHidden.get(ti);
  texHidden.set(ti, hide);
  try { core.setPartOpacityByIndex(pi, hide ? 0 : 1); } catch (e) {}
  renderLayerList();
}

function resetLayers() {
  if (!layerOrderArr || !layerNativeArr) return;
  layerOrderArr.set(layerNativeArr);
  texHidden.clear();
  try {
    const core = l2dModel.internalModel.coreModel;
    const n = core.getPartCount();
    for (let i = 0; i < n; i++) core.setPartOpacityByIndex(i, 1);
  } catch (e) {}
  autoFixNeckOrder();
  renderLayerList();
}

const shortId = (id) => String(id || "").length > 22
  ? String(id).slice(0, 21) + "…" : String(id || "");

function renderLayerList() {
  if (!layerOrderArr) return;
  const order = seqIndices().reverse();       // 显示顺序：最前面在上
  const groups = new Map();                   // 贴图序号 -> [drawableIdx...]（前→后）
  for (const di of order) {
    const ti = layerTex[di] ?? 0;
    if (!groups.has(ti)) groups.set(ti, []);
    groups.get(ti).push(di);
  }
  const rows = [...groups.entries()].map(([ti, dis]) => {
    const info = texInfo(ti);
    const hidden = !!texHidden.get(ti);
    const grpThumb = info.url
      ? `<img class="lgrpThumb" src="${info.url}" loading="lazy">`
      : `<span class="lgrpThumb ph"></span>`;
    return `<div class="lgrp" data-tex="${ti}">
      <div class="lgrpHead">
        ${grpThumb}
        <span class="lgrpName" title="${esc(info.name)}">${esc(info.name)}</span>
        <span class="lgrpCnt">${dis.length} 网格</span>
        <button class="mini" data-act="eye" data-tex="${ti}">${hidden ? "显示" : "隐藏"}</button>
        <button class="mini" data-act="edit" data-tex="${ti}"
          title="图片编辑：橡皮擦 / 圈选擦除 / 圈选剥离成配件 / 替换整图">✎ 图</button>
      </div>
      <div class="lrows">${dis.map(di => {
        const t = layerThumb[di];
        return `<div class="lrow" draggable="true" data-di="${di}"
                     style="opacity:${texHidden.get(ti) ? 0.35 : 1}">
          ${t ? `<img class="lthumb" src="${t}">` : `<span class="lthumb ph"></span>`}
          <span class="lname" title="${esc(layerIds[di])}">${esc(shortId(layerIds[di]))}</span>
          <button class="mini" data-act="up" title="向前一层">▲</button>
          <button class="mini" data-act="down" title="向后一层">▼</button>
        </div>`;
      }).join("")}</div>
    </div>`;
  }).join("");
  $("#layerList").innerHTML = rows;

  $$("#layerList .lrow button").forEach(b => b.onclick = (e) => {
    e.stopPropagation();
    const di = +b.closest(".lrow").dataset.di;
    if (b.dataset.act === "up") shiftLayer(di, +1);
    else shiftLayer(di, -1);
  });
  $$("#layerList .lgrpHead [data-act=eye]").forEach(b => b.onclick = (e) => {
    e.stopPropagation();
    toggleTexGroup(+b.dataset.tex);
  });
  $$("#layerList .lgrpHead [data-act=edit]").forEach(b => b.onclick = (e) => {
    e.stopPropagation();
    openTexEditor(+b.dataset.tex);
  });
  bindLayerDrag();
}

function bindLayerDrag() {
  let dragDi = null;
  $$("#layerList .lrow").forEach(el => {
    el.ondragstart = (e) => {
      dragDi = +el.dataset.di;
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", String(dragDi)); } catch (err) {}
    };
    el.ondragover = (e) => {
      e.preventDefault();
      el.classList.add("dragOver");
    };
    el.ondragleave = () => el.classList.remove("dragOver");
    el.ondrop = (e) => {
      e.preventDefault();
      el.classList.remove("dragOver");
      const target = +el.dataset.di;
      if (dragDi != null && dragDi !== target) moveTo(dragDi, target);
      dragDi = null;
    };
  });
  $("#layerList").ondragend = () => { dragDi = null; };
}

/* ---------------- 动画编辑器（Blender 式） ----------------
 * moc3 没有 BLender 那种骨架，这里用「参数组手柄」当骨骼：每个手柄锚定
 * 一个部件（drawable 质心），绑定若干参数通道（转头 X/Y/Z、眼睛开合…）。
 * 在画布上点选手柄 → 拖动按通道写参数值（X 轴写横向通道、Y 轴写纵向），
 * K 帧把「该骨骼所有通道的当前值」记成一帧；dope sheet 按骨骼分行显示。
 * 播放时在 beforeModelUpdate（motion/physics 之后、core.update 之前）
 * 插值写参数，优先级最高。保存时编成标准 motion3.json 进模型包。 */

// 骨骼定义：按参数 id 模式聚合，锚定部件名模式（生成模型的部件名很规整）
const BONE_DEFS = [
  { id: "head", name: "头部", anchor: /face_base|face/,
    chs: [
      { label: "转 X", ids: ["ParamAngleX"], axis: "x", sens: 0.15 },
      { label: "点 Y", ids: ["ParamAngleY"], axis: "y", sens: 0.15 },
      { label: "歪 Z", ids: ["ParamAngleZ"], axis: null, sens: 0.15 },
    ] },
  { id: "eyes", name: "眼睛", anchor: /eye_l$|eye_r$|eye(?!_w|_c)/,
    chs: [
      { label: "睁闭", ids: ["ParamEyeLOpen", "ParamEyeROpen"], axis: "y", sens: 0.004, zero: 1 },
      { label: "眯眼", ids: ["ParamEyeLSmile", "ParamEyeRSmile"], axis: null, sens: 0.004, zero: 0 },
      { label: "瞳 X", ids: ["ParamEyeBallX"], axis: null, sens: 0.005 },
      { label: "瞳 Y", ids: ["ParamEyeBallY"], axis: null, sens: 0.005 },
    ] },
  { id: "brows", name: "眉毛", anchor: /eyebrow/,
    chs: [
      { label: "挑眉", ids: ["ParamBrowLY", "ParamBrowRY"], axis: "y", sens: 0.006, zero: 0 },
      { label: "皱眉", ids: ["ParamBrowLForm", "ParamBrowRForm"], axis: null, sens: 0.006 },
    ] },
  { id: "mouth", name: "嘴", anchor: /12_mouth$|mouth(?!_c)/,
    chs: [
      { label: "张嘴", ids: ["ParamMouthOpenY"], axis: "y", sens: 0.004 },
      { label: "嘴形", ids: ["ParamMouthForm"], axis: null, sens: 0.005 },
    ] },
  { id: "body", name: "身体", anchor: /13_clothing|clothing(?!_)/,
    chs: [
      { label: "摆 X", ids: ["ParamBodyAngleX"], axis: "x", sens: 0.06 },
      { label: "倾 Y", ids: ["ParamBodyAngleY"], axis: "y", sens: 0.06 },
      { label: "扭 Z", ids: ["ParamBodyAngleZ"], axis: null, sens: 0.06 },
      { label: "呼吸", ids: ["ParamBreath"], axis: null, sens: 0.004 },
    ] },
  { id: "armL", name: "左臂", anchor: /arm_l/,
    chs: [
      { label: "抬 A", ids: ["ParamArmLA"], axis: "y", sens: 0.05, sign: 1 },
      { label: "摆 B", ids: ["ParamArmLB"], axis: "x", sens: 0.05, sign: -1 },
    ] },
  { id: "armR", name: "右臂", anchor: /arm_r/,
    chs: [
      { label: "抬 A", ids: ["ParamArmRA"], axis: "y", sens: 0.05, sign: 1 },
      { label: "摆 B", ids: ["ParamArmRB"], axis: "x", sens: 0.05, sign: -1 },
    ] },
  { id: "hairFront", name: "前发", anchor: /hair_front/,
    chs: [
      { label: "摆", ids: ["ParamHairFront"], axis: "x", sens: 0.005 },
      { label: "竖", ids: ["ParamHairFrontV"], axis: "y", sens: 0.005 },
    ] },
  { id: "hairBack", name: "后发", anchor: /hair_back/,
    chs: [
      { label: "摆", ids: ["ParamHairBack"], axis: "x", sens: 0.005 },
      { label: "竖", ids: ["ParamHairBackV"], axis: "y", sens: 0.005 },
    ] },
];

let boneOverlay = null;      // 画布上的手柄 DOM 容器

function hookBeforeUpdate(model) {
  try {
    const im = model.internalModel;
    im.on("beforeModelUpdate", () => {
      const core = im.coreModel;
      if (animState.playing) {
        for (const b of animState.bones) {
          for (const ch of b.chs) {
            const v = chAnimValueAt(b, ch, animState.t);
            if (v != null) for (const id of ch.ids) core.setParameterValueById(id, v);
          }
        }
      } else if (poseOverride.size) {
        for (const [id, v] of poseOverride) core.setParameterValueById(id, v);
      }
    });
  } catch (e) {}
}

function loadParams(model) {
  animState.params = [];
  try {
    const core = model.internalModel.coreModel;
    // 包装层没有 getParameterIds()（实测 Cubism5 core 的框架包装），
    // 只暴露私有的 _parameterIds；没有它就退回 cdi3 的参数表
    const ids = Array.isArray(core._parameterIds) ? core._parameterIds
      : (modelInfo?.parameters || []).map(p => p.id);
    const n = core.getParameterCount();
    const byId = new Map((modelInfo?.parameters || []).map(p => [p.id, p]));
    for (let i = 0; i < Math.max(n, ids.length); i++) {
      const id = ids[i];
      if (!id) continue;
      const p = byId.get(id);
      let min = null, max = null, def = null;
      try { min = core.getParameterMinimumValue(i); } catch (e) {}
      try { max = core.getParameterMaximumValue(i); } catch (e) {}
      try { def = core.getParameterDefaultValue(i); } catch (e) {}
      if (typeof min !== "number" || typeof max !== "number" || !(max > min)) { min = -1; max = 1; }
      if (typeof def !== "number" || def < min || def > max) def = (min + max) / 2;
      animState.params.push({ id, name: p?.name || id, group: p?.group || "", min, max, def });
    }
  } catch (e) { animState.params = []; }
}

// ---- 骨骼构建：把 BONE_DEFS 对齐到当前模型的参数与部件 ----
function buildBones(model) {
  const core = model.internalModel.coreModel;
  const pmap = new Map(animState.params.map(p => [p.id, p]));
  const drIds = Array.from({ length: core.getDrawableCount() }, (_, i) => core.getDrawableId(i));
  animState.bones = [];
  for (const def of BONE_DEFS) {
    const chs = [];
    for (const ch of def.chs) {
      const ids = ch.ids.filter(id => pmap.has(id));
      if (!ids.length) continue;
      const p0 = pmap.get(ids[0]);
      chs.push({ ...ch, ids,
        min: Math.min(...ids.map(id => pmap.get(id).min)),
        max: Math.max(...ids.map(id => pmap.get(id).max)),
        def: p0.def, step: Math.max((p0.max - p0.min) / 200, 0.01) });
    }
    if (!chs.length) continue;
    // 锚点：anchor 正则命中的第一个 drawable（前→后），找不到就挂画布中心
    let anchorIdx = drIds.findIndex((d, i) => def.anchor.test(d));
    animState.bones.push({
      id: def.id, name: def.name, chs, anchorIdx,
      show: true, keys: [],
    });
  }
  // 自定义骨骼：锚点是指定的 drawable id，缺参数的通道跳过
  for (const def of (animState.customDefs || [])) {
    const chs = [];
    for (const ch of (def.chs || [])) {
      const ids = (ch.ids || []).filter(id => pmap.has(id));
      if (!ids.length) continue;
      const p0 = pmap.get(ids[0]);
      chs.push({ ...ch, ids,
        min: Math.min(...ids.map(id => pmap.get(id).min)),
        max: Math.max(...ids.map(id => pmap.get(id).max)),
        def: p0.def, step: Math.max((p0.max - p0.min) / 200, 0.01) });
    }
    if (!chs.length) continue;
    const anchorIdx = def.anchorDrawable ? drIds.indexOf(def.anchorDrawable) : -1;
    animState.bones.push({
      id: def.id, name: def.name, chs, anchorIdx,
      show: true, keys: [], custom: true,
    });
  }
  animState.selected = null;
}

function boneById(id) { return animState.bones.find(b => b.id === id); }

// ---- 取值 / 插值 ----
function chVal(b, ch) {
  // 姿态的真值在 poseOverride（骨骼拖拽/滑杆写的），coreModel 只是它在
  // 下一帧渲染时的投影 —— 标签页在后台时投影会停更，所以打帧必须读这里
  const id = ch.ids[0];
  const ov = poseOverride.get(id);
  if (ov != null) return ov;
  if (!l2dModel) return ch.def;
  let v = null;
  try { v = l2dModel.internalModel.coreModel.getParameterValueById(id); } catch (e) {}
  return typeof v === "number" ? v : ch.def;
}

function boneKeyAt(b, t) {
  if (!b.keys.length) return null;
  if (t <= b.keys[0].t) return b.keys[0];
  const last = b.keys[b.keys.length - 1];
  if (t >= last.t) return last;
  for (let i = 0; i < b.keys.length - 1; i++) {
    if (t >= b.keys[i].t && t <= b.keys[i + 1].t) return b.keys[i];
  }
  return last;
}

// 播放时某通道在 t 的插值（同骨骼所有通道共用同一组帧时间）
function chAnimValueAt(b, ch, t) {
  const ks = b.keys;
  if (!ks.length) return null;
  const ci = b.chs.indexOf(ch);
  const lerp = (a, bb, f) => a + (bb - a) * f;
  if (t <= ks[0].t) return ks[0].vals[ci];
  if (t >= ks[ks.length - 1].t) return ks[ks.length - 1].vals[ci];
  for (let i = 0; i < ks.length - 1; i++) {
    const A = ks[i], B = ks[i + 1];
    if (t < A.t || t > B.t) continue;
    const f = B.t === A.t ? 1 : (t - A.t) / (B.t - A.t);
    if (B.mode === "step") return A.vals[ci];
    if (B.mode === "smooth") {
      const u = 1 - f;
      return u * u * u * A.vals[ci] + 3 * u * u * f * A.vals[ci]
        + 3 * u * f * f * B.vals[ci] + f * f * f * B.vals[ci];
    }
    return lerp(A.vals[ci], B.vals[ci], f);
  }
  return ks[ks.length - 1].vals[ci];
}

// ---- 播放循环 ----
function animTick() {
  if (animState.open && animState.playing) refreshBoneHandles();
  if (!animState.playing || !pixiApp) return;
  animState.t += pixiApp.ticker.deltaMS / 1000;
  const d = Math.max(animState.duration, 0.05);
  if (animState.t >= d) {
    if (animState.loop) animState.t %= d;
    else { animState.t = d; setPlaying(false); }
  }
  syncPlayheadUI();
}

function setPlaying(on) {
  animState.playing = on;
  const b = $("#btnPlay");
  if (b) b.textContent = on ? "⏸ 暂停" : "▶ 播放";
}

function syncPlayheadUI() {
  const d = Math.max(animState.duration, 0.001);
  const f = Math.min(1, Math.max(0, animState.t / d));
  const ph = $("#playhead");
  if (ph) ph.style.left = `calc(140px + (100% - 140px) * ${f.toFixed(4)})`;
  const tEl = $("#animTime");
  if (tEl) tEl.textContent = `${animState.t.toFixed(2)}s / ${animState.duration.toFixed(1)}s`;
}

function seek(t) {
  animState.t = Math.min(animState.duration, Math.max(0, t));
  // 播放头压在帧上时把姿态呈现出来（非播放态也可见）
  if (!animState.playing) {
    for (const b of animState.bones) {
      if (!b.keys.length) continue;
      for (const ch of b.chs) {
        const v = chAnimValueAt(b, ch, animState.t);
        if (v != null) for (const id of ch.ids) poseOverride.set(id, v);
      }
    }
    renderBoneList();
  }
  syncPlayheadUI();
}

// ---- 打帧 ----
function keyBone(b, t) {
  const tt = Math.round(t * 100) / 100;
  const vals = b.chs.map(ch => chVal(b, ch));
  const near = b.keys.find(k => Math.abs(k.t - tt) < 0.02);
  if (near) near.vals = vals;
  else { b.keys.push({ t: tt, vals, mode: "linear" }); b.keys.sort((a, x) => a.t - x.t); }
}

function keySelected() {
  const b = boneById(animState.selected);
  if (!b) { toast("先选中一个骨骼（画布上的圆点或左侧列表）", "err"); return; }
  keyBone(b, animState.t);
  renderBoneList(); renderDope();
  toast(`${b.name} 已在 ${animState.t.toFixed(2)}s 打帧`, "ok");
}

function keyAll() {
  // 有帧的、或本轮被拖动过（poseOverride 里有值）的骨骼都打帧
  const live = animState.bones.filter(b =>
    b.keys.length || b.chs.some(ch => ch.ids.some(id => poseOverride.has(id))));
  if (!live.length) { toast("还没有任何关键帧", "err"); return; }
  live.forEach(b => keyBone(b, animState.t));
  renderBoneList(); renderDope();
  toast(`${live.length} 个骨骼已打帧`, "ok");
}

function deleteSelectedFrame() {
  const b = boneById(animState.selected);
  if (!b || !b.keys.length) return;
  const t = animState.t;
  b.keys = b.keys.filter(k => Math.abs(k.t - t) >= 0.02);
  renderBoneList(); renderDope();
}

// ---- 骨骼手柄（画布覆盖层） ----
function drawableCentroid(core, idx) {
  const vp = core.getDrawableVertexPositions(idx);
  let cx = 0, cy = 0, n = 0;
  for (let k = 0; k < vp.length; k += 2) { cx += vp[k]; cy += vp[k + 1]; n++; }
  return n ? { x: cx / n, y: cy / n } : null;
}

function ensureBoneOverlay() {
  const wrap = document.querySelector("#l2d")?.parentElement;
  if (!wrap || boneOverlay?.parentElement === wrap) return;
  if (boneOverlay) boneOverlay.remove();
  boneOverlay = document.createElement("div");
  boneOverlay.className = "boneOverlay";
  wrap.appendChild(boneOverlay);
}

function refreshBoneHandles() {
  if (!animState.open || !l2dModel || !boneOverlay) return;
  const im = l2dModel.internalModel, core = im.coreModel;
  // 顶点坐标是模型单位（±1 量级），先按 pixelsPerUnit 换算成本地像素
  // （Y 轴向上要翻成屏幕向下），再经 toGlobal 走 Live2DModel 的位移/缩放
  const ppu = im.pixelsPerUnit || 500, W = im.width || 1000, H = im.height || 1000;
  const canvas = document.getElementById("l2d");
  const cr = canvas.getBoundingClientRect(), wr = boneOverlay.parentElement.getBoundingClientRect();
  let html = "";
  for (const b of animState.bones) {
    if (!b.show || b.anchorIdx == null || b.anchorIdx < 0) continue;
    const c = drawableCentroid(core, b.anchorIdx);
    if (!c) continue;
    const g = l2dModel.toGlobal({ x: c.x * ppu + W / 2, y: H / 2 - c.y * ppu });
    const x = g.x / cr.width * wr.width, y = g.y / cr.height * wr.height;
    const sel = b.id === animState.selected;
    html += `<div class="bHandle ${sel ? "sel" : ""}" data-bone="${b.id}"
      style="left:${x.toFixed(1)}px;top:${y.toFixed(1)}px" title="${esc(b.name)}">
      <i></i><span>${esc(b.name)}</span></div>`;
  }
  boneOverlay.innerHTML = html;
  $$(".bHandle", boneOverlay).forEach(el => {
    el.onpointerdown = (e) => {
      e.stopPropagation();
      selectBone(el.dataset.bone);
      startBoneDrag(e, el.dataset.bone);
    };
  });
}

function selectBone(id) {
  animState.selected = id;
  renderBoneList(); renderDope(); refreshBoneHandles();
}

function startBoneDrag(e, boneId) {
  const b = boneById(boneId);
  if (!b) return;
  setPlaying(false);
  const x0 = e.clientX, y0 = e.clientY;
  const chX = b.chs.find(c => c.axis === "x");
  const chY = b.chs.find(c => c.axis === "y");
  const start = {};
  for (const ch of b.chs) start[ch.label] = chVal(b, ch);
  const move = (ev) => {
    const dx = ev.clientX - x0, dy = ev.clientY - y0;
    for (const ch of b.chs) {
      let base = start[ch.label];
      let d = 0;
      if (ch === chX) d = dx * ch.sens * (ch.sign || 1);
      else if (ch === chY) d = -dy * ch.sens * (ch.sign || 1);   // 屏幕Y向下
      else continue;
      const v = Math.min(ch.max, Math.max(ch.min,
        (ch.zero != null ? ch.zero : base) + d));
      for (const id of ch.ids) poseOverride.set(id, v);
    }
    renderBoneList();
  };
  const up = () => {
    document.removeEventListener("pointermove", move);
    document.removeEventListener("pointerup", up);
    if (animState.autoKey) { keyBone(b, animState.t); renderDope(); }
  };
  document.addEventListener("pointermove", move);
  document.addEventListener("pointerup", up);
}

// ---- 左侧骨骼列表 ----
function renderBoneList() {
  const box = $("#boneList");
  if (!box) return;
  if (!animState.bones.length) {
    box.innerHTML = `<div class="empty">这个模型没有识别出可用的骨骼参数</div>`;
    return;
  }
  box.innerHTML = animState.bones.map(b => {
    const sel = b.id === animState.selected;
    const vals = b.chs.map(ch => `${ch.label} ${(+chVal(b, ch)).toFixed(1)}`).join(" · ");
    return `<div class="boneRow ${sel ? "sel" : ""}" data-bone="${b.id}">
      <div class="bHead">
        <span class="bName">${esc(b.name)}</span>
        <span class="bVals">${esc(vals)}</span>
        ${b.custom ? `<button class="mini" data-act="bedit" title="编辑这个自定义骨骼">改</button>` : ""}
        <button class="mini" data-act="vis" title="${b.show ? "隐藏手柄" : "显示手柄"}">${b.show ? "◉" : "○"}</button>
      </div>
      ${sel ? `<div class="boneSliders">${b.chs.map((ch, ci) => `
        <div class="bsRow"><span>${esc(ch.label)}</span>
          <input type="range" data-bone="${b.id}" data-ci="${ci}"
                 min="${ch.min}" max="${ch.max}" step="${ch.step}" value="${chVal(b, ch)}">
          <b>${(+chVal(b, ch)).toFixed(1)}</b></div>`).join("")}
      </div>` : ""}
    </div>`;
  }).join("");
  $$("#boneList .bHead").forEach(h => h.onclick = (e) => {
    if (e.target.dataset.act === "vis") return;
    if (e.target.dataset.act === "bedit") {
      e.stopPropagation();
      editCustomBone(h.closest(".boneRow").dataset.bone);
      return;
    }
    selectBone(h.closest(".boneRow").dataset.bone);
  });
  $$("#boneList [data-act=vis]").forEach(b => b.onclick = (e) => {
    e.stopPropagation();
    const bone = boneById(b.closest(".boneRow").dataset.bone);
    bone.show = !bone.show;
    renderBoneList(); refreshBoneHandles();
  });
  $$("#boneList .bsRow input").forEach(sl => {
    const b = boneById(sl.dataset.bone), ch = b?.chs[+sl.dataset.ci];
    if (!ch) return;
    sl.oninput = () => {
      const v = +sl.value;
      for (const id of ch.ids) poseOverride.set(id, v);
      sl.parentElement.querySelector("b").textContent = v.toFixed(1);
      const head = sl.closest(".boneRow").querySelector(".bVals");
      if (head) head.textContent = b.chs.map(c =>
        `${c.label} ${(+chVal(b, c)).toFixed(1)}`).join(" · ");
    };
    sl.onchange = () => { if (animState.autoKey) { keyBone(b, animState.t); renderDope(); } };
  });
}

// ---- dope sheet ----
function renderDope() {
  const names = $("#dopeNames"), bars = $("#dopeBars");
  if (!names || !bars) return;
  const d = Math.max(animState.duration, 0.001);
  const live = animState.bones;
  if (!live.length) {
    names.innerHTML = ""; bars.innerHTML = ""; return;
  }
  names.innerHTML = live.map(b =>
    `<div class="dName ${b.id === animState.selected ? "sel" : ""}" data-bone="${b.id}">
      <span>${esc(b.name)}</span>
      ${b.keys.length ? `<span class="kcnt">${b.keys.length}帧</span>` : ""}</div>`).join("");
  bars.innerHTML = live.map(b =>
    `<div class="dBar ${b.id === animState.selected ? "sel" : ""}" data-bone="${b.id}">
      ${b.keys.map((k, ki) => `<i class="kf m-${k.mode || "linear"}"
        data-bone="${b.id}" data-ki="${ki}" style="left:clamp(6px, ${(k.t / d * 100).toFixed(2)}%, calc(100% - 6px))"
        title="${k.t.toFixed(2)}s（拖动改时间 · 单击换缓动 · 右键删除）"></i>`).join("")}
    </div>`).join("");
  $$("#dopeNames .dName").forEach(el => el.onclick = () => selectBone(el.dataset.bone));
  $$("#dopeBars .dBar").forEach(bar => {
    bar.onpointerdown = (e) => {
      if (e.target.classList.contains("kf")) return;
      selectBone(bar.dataset.bone);
      setPlaying(false);
      seek(fracFromEvent(e, bar) * animState.duration);
    };
  });
  $$("#dopeBars .kf").forEach(bindDopeKf);
}

function fracFromEvent(e, el) {
  const rect = el.getBoundingClientRect();
  return Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
}

function bindDopeKf(el) {
  const boneId = el.dataset.bone, ki = +el.dataset.ki;
  el.onpointerdown = (e) => {
    e.stopPropagation(); e.preventDefault();
    const b = boneById(boneId);
    if (!b) return;
    selectBone(boneId);
    setPlaying(false);
    const bar = el.parentElement;
    const rect = bar.getBoundingClientRect();
    const x0 = e.clientX;
    let moved = false;
    const mv = (ev) => {
      if (Math.abs(ev.clientX - x0) > 3) moved = true;
      if (!moved || !b.keys[ki]) return;
      const f = fracFromEvent(ev, bar);
      b.keys[ki].t = Math.round(f * animState.duration * 100) / 100;
      el.style.left = `clamp(6px, ${(f * 100).toFixed(2)}%, calc(100% - 6px))`;
    };
    const up = () => {
      document.removeEventListener("pointermove", mv);
      document.removeEventListener("pointerup", up);
      if (moved) { b.keys.sort((a, x) => a.t - x.t); renderDope(); }
      else if (b.keys[ki]) {
        const k = b.keys[ki];
        k.mode = k.mode === "linear" ? "smooth" : k.mode === "smooth" ? "step" : "linear";
        renderDope();
      }
    };
    document.addEventListener("pointermove", mv);
    document.addEventListener("pointerup", up);
  };
  el.oncontextmenu = (e) => {
    e.preventDefault();
    const b = boneById(boneId);
    if (b) { b.keys.splice(ki, 1); renderBoneList(); renderDope(); }
  };
}

// ---- motion3 编码 / 保存 ----
function buildMotion3() {
  const r4 = (x) => Math.round(x * 10000) / 10000;
  const curves = [];
  let segs = 0, pts = 0, maxT = 0;
  for (const b of animState.bones) {
    if (!b.keys.length) continue;
    for (const ch of b.chs) {
      const ci = b.chs.indexOf(ch);
      const seg = [r4(b.keys[0].t), r4(b.keys[0].vals[ci])];
      for (let i = 1; i < b.keys.length; i++) {
        const a = b.keys[i - 1], kk = b.keys[i];
        const av = a.vals[ci], bv = kk.vals[ci];
        if (kk.mode === "step") seg.push(2, r4(kk.t), r4(bv));
        else if (kk.mode === "smooth") {
          const dt = kk.t - a.t;
          seg.push(1, r4(a.t + dt / 3), r4(av), r4(kk.t - dt / 3), r4(bv), r4(kk.t), r4(bv));
        } else seg.push(0, r4(kk.t), r4(bv));
      }
      curves.push({ Target: "Parameter", Id: ch.ids[0], Segments: seg });
      if (ch.ids.length > 1) {
        // 多参数通道：每帧值相同，其它参数各生成一条曲线
        for (let m = 1; m < ch.ids.length; m++) {
          const seg2 = [r4(b.keys[0].t), r4(b.keys[0].vals[ci])];
          for (let i = 1; i < b.keys.length; i++) {
            const kk = b.keys[i];
            seg2.push(0, r4(kk.t), r4(kk.vals[ci]));
          }
          curves.push({ Target: "Parameter", Id: ch.ids[m], Segments: seg2 });
        }
      }
      segs += b.keys.length - 1;
      pts += b.keys.length;
      maxT = Math.max(maxT, b.keys[b.keys.length - 1].t);
    }
  }
  return {
    Version: 3,
    Meta: { Duration: r4(Math.max(animState.duration, maxT)), Fps: 30.0,
            Loop: !!animState.loop, CurveCount: curves.length,
            TotalSegmentCount: segs, TotalPointCount: pts,
            UserDataCount: 0, TotalUserDataSize: 0 },
    Curves: curves,
  };
}

async function saveMotion() {
  if (!state.task) return;
  const name = $("#animName").value.trim();
  if (!name) { toast("先给动作起个名（如 nod、打招呼）", "err"); return; }
  if (!animState.bones.some(b => b.keys.length)) { toast("还没有关键帧（拖骨骼后按 K）", "err"); return; }
  try {
    await api(`/api/tasks/${state.task.id}/motions`, {
      method: "POST", body: JSON.stringify({ name, motion: buildMotion3() }) });
    toast(`已保存「${name}」，重新加载模型…`, "ok");
    await loadModel(loadedModelUrl, true);   // 新登记的动作要重载模型才可见
  } catch (e) { toast("保存失败：" + e.message, "err"); }
}

async function refreshMotions() {
  if (!state.task) return;
  try {
    const r = await api(`/api/tasks/${state.task.id}/motions`);
    animState.motions = r.motions || [];
  } catch (e) { animState.motions = []; }
  renderMotionList();
}

function renderMotionList() {
  const box = $("#motionList");
  if (!box) return;
  if (!animState.motions.length) { box.innerHTML = ""; return; }
  const cnt = new Map();
  const list = animState.motions.map(m => {
    const gi = cnt.get(m.group) || 0; cnt.set(m.group, gi + 1);
    return { ...m, gi };
  });
  box.innerHTML = `<span class="mTitle">动作库（点▶播放）：</span>` +
    list.map((m, i) => `<span class="mItem">
      <button class="mini" data-act="play" data-i="${i}">▶ ${esc(m.name)}</button>
      ${m.editable ? `<button class="mini danger" data-act="del" data-i="${i}"
        title="删除自定义动作">×</button>` : ""}
    </span>`).join("");
  $$("#motionList [data-act=play]").forEach(b => b.onclick = async () => {
    const m = list[+b.dataset.i];
    setPlaying(false);
    poseOverride.clear();
    try { await l2dModel?.motion(m.group, m.gi, 3); }
    catch (e) { toast("播放失败：" + e.message, "err"); }
  });
  $$("#motionList [data-act=del]").forEach(b => b.onclick = async () => {
    const m = list[+b.dataset.i];
    if (!confirm(`删除自定义动作「${m.name}」？`)) return;
    try {
      await api(`/api/tasks/${state.task.id}/motions/${encodeURIComponent(m.name)}`,
                { method: "DELETE" });
      toast("已删除", "ok");
      await loadModel(loadedModelUrl, true);
    } catch (e) { toast("删除失败：" + e.message, "err"); }
  });
}

function renderAnimPanel() {
  $("#animDur").value = animState.duration;
  $("#animLoop").checked = animState.loop;
  $("#animAutoKey").checked = animState.autoKey;
  renderBoneList();
  renderDope();
  syncPlayheadUI();
  renderMotionList();
  refreshBoneHandles();
}

function bindAnimPanel() {
  $("#btnPlay").onclick = () => {
    if (!animState.bones.some(b => b.keys.length)) { toast("先打关键帧再播放（拖骨骼后按 K）", "err"); return; }
    setPlaying(!animState.playing);
    if (animState.playing) poseOverride.clear();
  };
  $("#animDur").onchange = (e) => {
    animState.duration = Math.min(30, Math.max(0.5, +e.target.value || 3));
    e.target.value = animState.duration;
    renderDope(); syncPlayheadUI();
  };
  $("#animLoop").onchange = (e) => { animState.loop = e.target.checked; };
  $("#animAutoKey").onchange = (e) => { animState.autoKey = e.target.checked; };
  $("#btnKf").onclick = keySelected;
  $("#btnKfAll").onclick = keyAll;
  $("#btnKfClear").onclick = deleteSelectedFrame;
  $("#btnClearTracks").onclick = () => {
    animState.bones.forEach(b => b.keys = []);
    renderBoneList(); renderDope();
  };
  $("#btnSaveMotion").onclick = saveMotion;
  // 时间尺与 dope 区点击 = 拖播放头
  const dragHead = (e) => {
    setPlaying(false);
    const move = (ev) => seek(fracFromEvent(ev, e.currentTarget) * animState.duration);
    move(e);
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
  };
  $("#dopeRuler").onpointerdown = dragHead;
  // 快捷键：Space 播放 / K 打帧（输入框聚焦或弹窗打开时不抢）
  document.addEventListener("keydown", (e) => {
    if (!animState.open) return;
    if (!$("#modalMask").hidden) return;
    const tag = document.activeElement?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (e.code === "Space") { e.preventDefault(); $("#btnPlay").click(); }
    else if (e.key === "k" || e.key === "K") keySelected();
    else if (e.key === "Delete" || e.key === "Backspace") deleteSelectedFrame();
  });
}

function fit() {
  if (!l2dModel || !pixiApp) return;
  const w = pixiApp.renderer.width / pixiApp.renderer.resolution;
  const h = pixiApp.renderer.height / pixiApp.renderer.resolution;
  const s = Math.min(w / l2dModel.internalModel.width, h / l2dModel.internalModel.height) * 0.92;
  l2dModel.scale.set(s);
  l2dModel.position.set(w / 2, (h - l2dModel.internalModel.height * s) / 2 + 4);
  refreshBoneHandles();
}

/* ---------------- 工作台子页签 ----------------
 * 动画编辑与图层管理原来上下堆着，编辑要来回滚动；
 * 现在拆成同一面板里的两个子页，切页显示，画布始终可见 */
function setTab(tab) {
  state.uiTab = tab;
  $$(".wbTab").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  $("#wbPageAnim").hidden = tab !== "anim";
  $("#wbPageLayers").hidden = tab !== "layers";
  $("#wbHint").textContent = tab === "anim"
    ? "拖骨骼摆姿势 → K 打帧 → ▶ 播放（Space 播放 / K 打帧）"
    : "按部件分组 · 上 = 最前 · 拖动网格行排序 · 「✎ 图」进入图片编辑";
  animState.open = tab === "anim";
  if (animState.open) { ensureBoneOverlay(); renderAnimPanel(); }
  else if (boneOverlay) boneOverlay.innerHTML = "";
}

/* ---------------- 自定义骨骼 ----------------
 * 内置 BONE_DEFS 覆盖不到的部位（裙子、飘带、尾巴…）可以自己加：
 * 锚点 = 任选一个网格（手柄画在其质心），通道 = 绑任意参数 + 拖动轴 + 灵敏度。
 * 定义持久化在模型包 custom_bones.json，导出后仍在。 */
async function loadCustomBones() {
  if (!state.task) return;
  try {
    const r = await api(`/api/tasks/${state.task.id}/custom-bones`);
    animState.customDefs = Array.isArray(r.bones) ? r.bones : [];
  } catch (e) { animState.customDefs = animState.customDefs || []; }
}

async function saveCustomBones() {
  if (!state.task) return;
  try {
    await api(`/api/tasks/${state.task.id}/custom-bones`, {
      method: "POST", body: JSON.stringify({ bones: animState.customDefs }) });
  } catch (e) { toast("自定义骨骼保存失败：" + e.message, "err"); }
}

let boneEditing = null;   // 正在编辑的自定义骨骼 def（null = 新建）

function editCustomBone(boneId) {
  const def = (animState.customDefs || []).find(d => d.id === boneId);
  if (def) openBoneModal(def);
}

function anchorOptions(cur) {
  if (!layerIds.length) return `<option value="">（画布中心）</option>`;
  const groups = new Map();
  layerIds.forEach((id, i) => {
    const ti = layerTex[i] ?? 0;
    if (!groups.has(ti)) groups.set(ti, []);
    groups.get(ti).push(i);
  });
  let html = `<option value="" ${!cur ? "selected" : ""}>（画布中心）</option>`;
  for (const [ti, dis] of groups) {
    html += `<optgroup label="${esc(texInfo(ti).name)}">` + dis.map(i =>
      `<option value="${esc(layerIds[i])}" ${layerIds[i] === cur ? "selected" : ""}>
        ${esc(shortId(layerIds[i]))}</option>`).join("") + `</optgroup>`;
  }
  return html;
}

function paramOptions(cur) {
  return animState.params.map(p =>
    `<option value="${esc(p.id)}" ${p.id === cur ? "selected" : ""}>
      ${esc(p.name || p.id)} · ${esc(p.id)}</option>`).join("");
}

function chRowHtml(ch) {
  return `<div class="bfChRow">
    <select class="bfParam">${paramOptions(ch?.ids?.[0])}</select>
    <select class="bfAxis">
      <option value="x" ${ch?.axis === "x" ? "selected" : ""}>横向拖</option>
      <option value="y" ${ch?.axis === "y" ? "selected" : ""}>纵向拖</option>
      <option value="" ${!ch?.axis ? "selected" : ""}>不拖</option>
    </select>
    <input class="bfSens" type="number" step="0.01" min="0.001" value="${ch?.sens ?? 0.1}" title="每拖 1px 的参数增量">
    <button class="mini" data-act="delch" title="删除该通道">×</button>
  </div>`;
}

function openBoneModal(def) {
  boneEditing = def || null;
  $("#boneModalTitle").textContent = def ? `编辑骨骼 · ${def.name}` : "新增自定义骨骼";
  $("#btnBoneDelete").hidden = !def;
  $("#boneFormBody").innerHTML = `
    <div class="bfGroup"><span>骨骼名</span>
      <input id="bfName" maxlength="12" value="${esc(def?.name || "")}" placeholder="如 裙摆、飘带"></div>
    <div class="bfGroup"><span>锚点网格（手柄显示在该网格质心，找不到就挂画布中心）</span>
      <select id="bfAnchor">${anchorOptions(def?.anchorDrawable)}</select></div>
    <div class="bfChHead">参数通道：横向/纵向拖动手柄写对应参数，灵敏度 = 每像素参数增量</div>
    <div id="bfChs">${(def?.chs || [null]).map(chRowHtml).join("")}</div>
    <button class="mini" id="bfAddCh">＋加通道</button>`;
  $("#bfAddCh").onclick = () => {
    const box = $("#bfChs");
    if (box.children.length >= 5) { toast("最多 5 个通道", "err"); return; }
    box.insertAdjacentHTML("beforeend", chRowHtml(null));
    bindChRows();
  };
  bindChRows();
  openModal("bone");
}

function bindChRows() {
  $$("#bfChs [data-act=delch]").forEach(b => b.onclick = () => {
    const rows = $$("#bfChs .bfChRow");
    if (rows.length <= 1) { toast("至少留一个通道", "err"); return; }
    b.closest(".bfChRow").remove();
  });
}

async function saveBoneForm() {
  const name = $("#bfName").value.trim();
  if (!name) { toast("给骨骼起个名", "err"); return; }
  const chs = $$("#bfChs .bfChRow").map(row => {
    const pid = row.querySelector(".bfParam").value;
    const axis = row.querySelector(".bfAxis").value || null;
    const sens = +row.querySelector(".bfSens").value || 0.1;
    const p = animState.params.find(x => x.id === pid);
    return { label: p?.name || pid, ids: [pid], axis, sens };
  }).filter(ch => ch.ids[0]);
  if (!chs.length) { toast("每个骨骼至少要绑一个有效参数", "err"); return; }
  const def = {
    id: boneEditing?.id || ("c_" + Date.now().toString(36)),
    name,
    anchorDrawable: $("#bfAnchor").value || "",
    chs,
  };
  const i = animState.customDefs.findIndex(d => d.id === def.id);
  if (i >= 0) animState.customDefs[i] = def;
  else animState.customDefs.push(def);
  await saveCustomBones();
  const selId = def.id;
  buildBones(l2dModel);          // 保留同 id 关键帧（prevKeys 机制）
  closeModal();
  selectBone(selId);
  renderAccList();
  toast(`骨骼「${name}」已保存：拖画布手柄摆姿势，K 打帧`, "ok");
}

async function deleteBoneForm() {
  if (!boneEditing) return;
  if (!confirm(`删除自定义骨骼「${boneEditing.name}」？其关键帧一并删除。`)) return;
  animState.customDefs = animState.customDefs.filter(d => d.id !== boneEditing.id);
  await saveCustomBones();
  buildBones(l2dModel);
  closeModal();
  renderBoneList(); renderDope(); refreshBoneHandles(); renderAccList();
  toast("已删除", "ok");
}

/* ---------------- 配件（PNG 跟随骨骼，权重可调） ----------------
 * 锚点 = 绑定骨骼的网格质心；weight=1 完全跟随，0 钉在画布中心。
 * 可在画布上直接拖动配件调偏移；层级可选在模型前/后。 */
function accPayload() {
  return accState.list.map(a => ({
    name: a.name, file: a.file, bone: a.bone || "", anchor: a.anchor || "",
    dx: +(a.dx || 0).toFixed(2), dy: +(a.dy || 0).toFixed(2),
    scale: +(a.scale ?? 0.3), rot: +(a.rot || 0),
    weight: +(a.weight ?? 1), front: a.front !== false, show: a.show !== false,
  }));
}

let accSaveTimer = null;
function saveAccessories() {
  clearTimeout(accSaveTimer);
  accSaveTimer = setTimeout(async () => {
    if (!state.task) return;
    try {
      await api(`/api/tasks/${state.task.id}/accessories`, {
        method: "PUT", body: JSON.stringify({ items: accPayload() }) });
    } catch (e) { toast("配件保存失败：" + e.message, "err"); }
  }, 350);
}

function resolveAnchorDrawable(boneId) {
  const b = boneById(boneId);
  if (!b || b.anchorIdx == null || b.anchorIdx < 0 || !layerIds.length) return "";
  return layerIds[b.anchorIdx] || "";
}

function placeAcc(a, spr) {
  const stage = pixiApp.stage;
  if (a.front === false) stage.addChildAt(spr, Math.max(0, stage.getChildIndex(l2dModel)));
  else stage.addChild(spr);
}

function makeAccSprite(a) {
  if (!pixiApp || !a.url) return;
  try {
    const spr = new PIXI.Sprite(PIXI.Texture.from(a.url));
    spr.anchor.set(0.5);
    spr.eventMode = "static";
    spr.cursor = "grab";
    placeAcc(a, spr);
    spr.on("pointerdown", (e) => {
      selectAcc(accState.list.indexOf(a));
      setPlaying(false);
      const sx = e.global.x, sy = e.global.y, dx0 = a.dx || 0, dy0 = a.dy || 0;
      a._drag = true;
      spr.cursor = "grabbing";
      const mv = (ev) => {
        const s = (l2dModel?.scale.x) || 1;   // 屏幕像素差换算回模型像素
        a.dx = dx0 + (ev.global.x - sx) / s;
        a.dy = dy0 + (ev.global.y - sy) / s;
      };
      const up = () => {
        a._drag = false;
        spr.cursor = "grab";
        spr.off("pointermove", mv);
        spr.off("pointerup", up);
        spr.off("pointerupoutside", up);
        saveAccessories();
        renderAccList();
      };
      spr.on("pointermove", mv);
      spr.on("pointerup", up);
      spr.on("pointerupoutside", up);
    });
    a.sprite = spr;
    accState.sprites.push(spr);
  } catch (e) {}
}

function destroyAccSprites() {
  for (const s of accState.sprites) {
    try { s.parent?.removeChild(s); s.destroy({ texture: true }); } catch (e) {}
  }
  accState.sprites = [];
}

async function loadAccessories() {
  if (!state.task) return;
  destroyAccSprites();
  try {
    const r = await api(`/api/tasks/${state.task.id}/accessories`);
    accState.list = (r.items || []).map(a => ({
      ...a, url: a.file ? fileUrl(a.file) : "" }));
  } catch (e) { accState.list = []; }
  accState.sel = null;
  for (const a of accState.list) if (a.show !== false) makeAccSprite(a);
  renderAccList();
}

async function addAccessoryFromFile(file, name) {
  if (!state.task) { toast("先加载模型", "err"); return; }
  const fd = new FormData();
  fd.append("file", file, (name || "acc") + ".png");
  try {
    const r = await fetch(`/api/tasks/${state.task.id}/accessories`,
      { method: "POST", body: fd });
    if (!r.ok) throw new Error((await r.text()).slice(0, 200));
    const j = await r.json();
    const a = {
      name: j.name, file: j.file, url: fileUrl(j.file),
      bone: animState.bones[0]?.id || "", anchor: resolveAnchorDrawable(animState.bones[0]?.id),
      dx: 0, dy: 0, scale: 0.3, rot: 0, weight: 1, front: true, show: true,
    };
    accState.list.push(a);
    makeAccSprite(a);
    accState.sel = accState.list.length - 1;
    await saveAccessories();
    renderAccList();
    return a;
  } catch (e) { toast("配件上传失败：" + e.message, "err"); return null; }
}

function boneLabelOf(a) {
  return a.bone ? (boneById(a.bone)?.name || a.bone) : "画布中心";
}

function selectAcc(i) {
  accState.sel = i;
  renderAccList();
}

function accPropsHtml(a) {
  const opts = animState.bones.map(b =>
    `<option value="${esc(b.id)}" ${b.id === a.bone ? "selected" : ""}>${esc(b.name)}</option>`).join("");
  return `<div class="accProps">
    <span>骨骼</span>
    <select class="apBind" style="grid-column:2/4">
      ${opts}<option value="" ${!a.bone ? "selected" : ""}>（画布中心）</option>
    </select>
    <span>权重</span>
    <input type="range" class="apW" min="0" max="1" step="0.05" value="${a.weight ?? 1}">
    <b>${(a.weight ?? 1).toFixed(2)}</b>
    <span>缩放</span>
    <input type="range" class="apS" min="0.05" max="3" step="0.05" value="${a.scale ?? 0.3}">
    <b>${(a.scale ?? 0.3).toFixed(2)}</b>
    <span>旋转°</span>
    <input type="range" class="apR" min="-180" max="180" step="5" value="${a.rot || 0}">
    <b>${Math.round(a.rot || 0)}</b>
    <span>偏移X</span>
    <input type="range" class="apDX" min="-300" max="300" step="1" value="${Math.round(a.dx || 0)}">
    <b>${Math.round(a.dx || 0)}</b>
    <span>偏移Y</span>
    <input type="range" class="apDY" min="-300" max="300" step="1" value="${Math.round(a.dy || 0)}">
    <b>${Math.round(a.dy || 0)}</b>
    <div class="accWide">
      <label><input type="checkbox" class="apFront" ${a.front !== false ? "checked" : ""}> 模型前</label>
      <label><input type="checkbox" class="apShow" ${a.show !== false ? "checked" : ""}> 显示</label>
      <span class="spacer"></span>
      <button class="mini danger apDel">删除</button>
    </div>
  </div>`;
}

function renderAccList() {
  const box = $("#accList");
  if (!box) return;
  if (!accState.list.length) {
    box.innerHTML = `<div class="empty" style="padding:10px 0">暂无配件<br>
      <span style="font-size:11px">上传 PNG 或在图层页「圈选剥离」生成</span></div>`;
    return;
  }
  box.innerHTML = accState.list.map((a, i) => `
    <div class="accRow ${i === accState.sel ? "sel" : ""} ${a.show === false ? "off" : ""}" data-i="${i}">
      <div class="accHead2">
        ${a.url ? `<img class="accThumb" src="${a.url}">` : `<span class="accThumb ph"></span>`}
        <span class="accName" title="${esc(a.name)}">${esc(a.name)}</span>
        <span class="accMeta">${esc(boneLabelOf(a))} · ${(a.weight ?? 1).toFixed(2)}</span>
      </div>
      ${i === accState.sel ? accPropsHtml(a) : ""}
    </div>`).join("");
  $$("#accList .accHead2").forEach(h => h.onclick = () =>
    selectAcc(+h.closest(".accRow").dataset.i));
  $$("#accList .accRow").forEach(row => {
    const i = +row.dataset.i, a = accState.list[i];
    const bind = row.querySelector(".apBind");
    if (!bind) return;
    bind.onchange = () => {
      a.bone = bind.value;
      a.anchor = resolveAnchorDrawable(a.bone);
      saveAccessories(); renderAccList();
    };
    const bindRange = (cls, key, fmt) => {
      const el = row.querySelector(cls);
      if (!el) return;
      el.oninput = () => {
        a[key] = +el.value;
        const b = el.parentElement.querySelector("b");
        if (b) b.textContent = fmt(+el.value);
      };
      el.onchange = () => saveAccessories();
    };
    bindRange(".apW", "weight", v => v.toFixed(2));
    bindRange(".apS", "scale", v => v.toFixed(2));
    bindRange(".apR", "rot", v => Math.round(v));
    bindRange(".apDX", "dx", v => Math.round(v));
    bindRange(".apDY", "dy", v => Math.round(v));
    row.querySelector(".apFront").onchange = (e) => {
      a.front = e.target.checked;
      placeAcc(a, a.sprite);
      saveAccessories();
    };
    row.querySelector(".apShow").onchange = (e) => {
      a.show = e.target.checked;
      row.classList.toggle("off", !a.show);
      saveAccessories();
    };
    row.querySelector(".apDel").onclick = () => {
      if (!confirm(`删除配件「${a.name}」？`)) return;
      try { a.sprite?.parent?.removeChild(a.sprite); a.sprite?.destroy({ texture: true }); } catch (err) {}
      accState.sprites = accState.sprites.filter(s => s !== a.sprite);
      accState.list.splice(i, 1);
      accState.sel = null;
      saveAccessories();
      renderAccList();
    };
  });
}

// 每帧把配件摆到绑定骨骼的质心（含偏移/权重/缩放/旋转）
function updateAccessories() {
  if (!l2dModel || !pixiApp || !accState.list.length) return;
  const w = pixiApp.renderer.width / pixiApp.renderer.resolution;
  const h = pixiApp.renderer.height / pixiApp.renderer.resolution;
  const cx = w / 2, cy = h / 2;
  const im = l2dModel.internalModel, core = im.coreModel;
  const ppu = im.pixelsPerUnit || 500, W = im.width || 1000, H = im.height || 1000;
  for (const a of accState.list) {
    const spr = a.sprite;
    if (!spr) continue;
    if (a.show === false) { spr.visible = false; continue; }
    spr.visible = true;
    let t = null;
    if (a.anchor) {
      const idx = layerIds.indexOf(a.anchor);
      if (idx >= 0) {
        const c = drawableCentroid(core, idx);
        if (c) t = l2dModel.toGlobal({ x: c.x * ppu + W / 2, y: H / 2 - c.y * ppu });
      }
    }
    if (!t) t = l2dModel.toGlobal({ x: W / 2, y: H / 2 });
    const k = a._drag ? 1 : (a.weight == null ? 1 : a.weight);
    const tx = t.x + (a.dx || 0) * l2dModel.scale.x;
    const ty = t.y + (a.dy || 0) * l2dModel.scale.y;
    spr.position.set(cx + (tx - cx) * k, cy + (ty - cy) * k);
    spr.scale.set((a.scale ?? 0.3) * l2dModel.scale.x);
    spr.rotation = (a.rot || 0) * Math.PI / 180;
  }
}

/* ---------------- 图片编辑器（图层页「✎ 图」） ----------------
 * 橡皮擦 / 圈选擦除：把 AI 没抠干净的图修掉；
 * 圈选剥离：把饰品等整块剪成独立配件 PNG（自动进配件列表，去动画页绑骨骼）；
 * 替换整图：换成本地图片。保存后写回模型包贴图并热重载。 */
const texEd = { ti: null, path: "", tool: "brush", undo: [], drawing: false,
                lasso: null, snap: null, img: null };

function setTexTool(t) {
  texEd.tool = t;
  $$(".ttool").forEach(b => b.classList.toggle("active", b.dataset.t === t));
  $("#texHint").textContent =
    t === "brush" ? "按住左键拖动，把不要的部分擦成透明" :
    t === "lassoErase" ? "在图上圈一圈，松手把圈内整体擦成透明" :
    "圈选饰品/物品，松手剥离成配件（原图不动，去动画页绑骨骼）";
}

function openTexEditor(ti) {
  const info = texInfo(ti);
  if (!info.url) { toast("找不到贴图文件", "err"); return; }
  texEd.ti = ti;
  texEd.path = info.url;
  texEd.undo = [];
  $("#texTitle").textContent = "图片编辑 · " + info.name;
  $("#btnTexUndo").disabled = true;
  const img = new Image();
  img.onload = () => {
    texEd.img = img;
    const c = $("#texCanvas");
    c.width = img.naturalWidth;
    c.height = img.naturalHeight;
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.drawImage(img, 0, 0);
    setTexTool("brush");
    openModal("tex");
  };
  img.onerror = () => toast("贴图加载失败", "err");
  img.src = info.url + (info.url.includes("?") ? "&" : "?") + "v=" + Date.now();
}

function texPos(e) {
  const c = $("#texCanvas"), r = c.getBoundingClientRect();
  const s = c.width / r.width;
  return { x: (e.clientX - r.left) * s, y: (e.clientY - r.top) * s };
}

function pushTexUndo() {
  const c = $("#texCanvas");
  texEd.undo.push(c.toDataURL());
  if (texEd.undo.length > 15) texEd.undo.shift();
  $("#btnTexUndo").disabled = false;
}

function undoTex() {
  const url = texEd.undo.pop();
  if (!url) return;
  const c = $("#texCanvas"), ctx = c.getContext("2d");
  const img = new Image();
  img.onload = () => { ctx.clearRect(0, 0, c.width, c.height); ctx.drawImage(img, 0, 0); };
  img.src = url;
  $("#btnTexUndo").disabled = !texEd.undo.length;
}

function strokeTex(from, to) {
  const c = $("#texCanvas"), ctx = c.getContext("2d");
  ctx.globalCompositeOperation = "destination-out";
  ctx.lineWidth = +$("#texBrush").value;
  ctx.lineCap = "round"; ctx.lineJoin = "round";
  ctx.beginPath();
  ctx.moveTo(from.x, from.y);
  ctx.lineTo(to.x, to.y);
  ctx.stroke();
  ctx.globalCompositeOperation = "source-over";
}

function polyPath(ctx, poly) {
  ctx.beginPath();
  ctx.moveTo(poly[0].x, poly[0].y);
  for (let i = 1; i < poly.length; i++) ctx.lineTo(poly[i].x, poly[i].y);
  ctx.closePath();
}

function erasePolygon(poly) {
  const c = $("#texCanvas"), ctx = c.getContext("2d");
  ctx.save();
  ctx.globalCompositeOperation = "destination-out";
  polyPath(ctx, poly);
  ctx.fill();
  ctx.restore();
}

function applyLasso(poly) {
  const c = $("#texCanvas"), ctx = c.getContext("2d");
  ctx.putImageData(texEd.snap, 0, 0);       // 去掉红框预览
  if (poly.length < 3) return;
  if (texEd.tool === "lassoErase") {
    erasePolygon(poly);
    return;
  }
  // 圈选剥离：bbox 裁剪 + clip 多边形 → 独立 PNG 配件
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const p of poly) {
    x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y);
    x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y);
  }
  x0 = Math.max(0, x0 - 4); y0 = Math.max(0, y0 - 4);
  x1 = Math.min(c.width, x1 + 4); y1 = Math.min(c.height, y1 + 4);
  if (x1 - x0 < 2 || y1 - y0 < 2) return;
  const out = document.createElement("canvas");
  out.width = Math.round(x1 - x0);
  out.height = Math.round(y1 - y0);
  const octx = out.getContext("2d");
  octx.translate(-x0, -y0);
  polyPath(octx, poly);
  octx.clip();
  octx.drawImage(c, 0, 0);
  out.toBlob(async (blob) => {
    if (!blob) return;
    const info = texInfo(texEd.ti);
    const a = await addAccessoryFromFile(
      new File([blob], "peel.png", { type: "image/png" }),
      `${info.name}_剥离`);
    if (a) toast(`已剥离为配件「${a.name}」，去动画页绑定骨骼、调权重`, "ok");
  }, "image/png");
}

function texDown(e) {
  if (!texEd.img) return;
  e.preventDefault();
  const p = texPos(e);
  pushTexUndo();
  if (texEd.tool === "brush") {
    texEd.drawing = true;
    texEd.last = p;
    strokeTex(p, { x: p.x + 0.01, y: p.y });
  } else {
    const c = $("#texCanvas");
    texEd.snap = c.getContext("2d").getImageData(0, 0, c.width, c.height);
    texEd.lasso = [p];
    texEd.drawing = true;
  }
  try { $("#texCanvas").setPointerCapture(e.pointerId); } catch (err) {}
}

function texMove(e) {
  if (!texEd.drawing) return;
  const p = texPos(e);
  if (texEd.tool === "brush") {
    strokeTex(texEd.last, p);
    texEd.last = p;
  } else if (texEd.lasso) {
    texEd.lasso.push(p);
    const c = $("#texCanvas"), ctx = c.getContext("2d");
    ctx.putImageData(texEd.snap, 0, 0);
    ctx.save();
    ctx.strokeStyle = "#ff7f2a";
    ctx.lineWidth = Math.max(2, c.width / 400);
    polyPath(ctx, texEd.lasso);
    ctx.stroke();
    ctx.restore();
  }
}

function texUp() {
  if (!texEd.drawing) return;
  texEd.drawing = false;
  if (texEd.lasso) {
    const poly = texEd.lasso;
    texEd.lasso = null;
    applyLasso(poly);
  }
}

async function saveTexture() {
  if (!texEd.path) return;
  const c = $("#texCanvas");
  try {
    await api(`/api/tasks/${state.task.id}/textures/save`, {
      method: "POST",
      body: JSON.stringify({ path: texEd.path, image: c.toDataURL("image/png") }) });
    try { await fetch(fileUrl(texEd.path), { cache: "reload" }); } catch (e) {}
    closeModal();
    toast("贴图已保存，正在重载模型…", "ok");
    await loadModel(loadedModelUrl, true);
  } catch (e) { toast("保存失败：" + e.message, "err"); }
}

function replaceTexture(file) {
  const c = $("#texCanvas");
  if (!c.width) return;
  const url = URL.createObjectURL(file);
  const img = new Image();
  img.onload = () => {
    pushTexUndo();
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, c.width, c.height);
    // cover 铺满：保持宽高比裁掉多余部分
    const s = Math.max(c.width / img.naturalWidth, c.height / img.naturalHeight);
    const w = img.naturalWidth * s, h = img.naturalHeight * s;
    ctx.drawImage(img, (c.width - w) / 2, (c.height - h) / 2, w, h);
    URL.revokeObjectURL(url);
  };
  img.src = url;
}

/* ---------------- 设置面板 ---------------- */
const SET_SCHEMA = [
  { group: "外部工具", items: [
    { k: "see_through_path", l: "see-through 路径", t: "path" },
    { k: "image2live2d_path", l: "image2live2d 路径", t: "path" },
    { k: "python_exec", l: "Python 解释器", t: "path", h: "跑工具用的解释器，留空用当前环境" },
  ]},
  { group: "生图", items: [
    { k: "gen_mode", l: "默认方式", t: "select", o: ["upload", "api", "comfyui"] },
    { k: "api_base", l: "API 地址", t: "text", h: "OpenAI 兼容端点，如 https://xxx/v1" },
    { k: "api_key", l: "API Key", t: "password", h: "单独存本地 secrets.json，不进 config.json" },
    { k: "api_model", l: "模型名", t: "text" },
    { k: "comfyui_url", l: "ComfyUI 地址", t: "text" },
    { k: "comfyui_workflow", l: "ComfyUI workflow", t: "textarea", h: "API format JSON，会自动替换提示词与 seed" },
    { k: "positive_suffix", l: "正向后缀", t: "textarea", h: "务必含 a-pose / full body / simple background" },
    { k: "negative_prompt", l: "负向提示", t: "textarea" },
  ]},
  { group: "分层", items: [
    { k: "decomp_precision", l: "精度", t: "select", o: ["auto", "bf16", "nf4"] },
    { k: "decomp_resolution", l: "分辨率", t: "select", o: ["768", "1024", "1280"] },
    { k: "decomp_depth_resolution", l: "深度分辨率", t: "text" },
    { k: "decomp_steps", l: "推理步数", t: "text" },
    { k: "decomp_group_offload", l: "group_offload", t: "check", h: "12GB 以下显存建议开（NF4 会强制关闭）" },
  ]},
  { group: "绑骨 / 服务", items: [
    { k: "rig_emit_live2d", l: "输出 Live2D 包", t: "check" },
    { k: "host", l: "监听地址", t: "text" },
    { k: "port", l: "端口", t: "text", h: "改端口需重启服务生效" },
  ]},
];

function renderSettings() {
  $("#setBody").innerHTML = SET_SCHEMA.map(g => `<div class="setGroup"><h4>${g.group}</h4>${
    g.items.map(it => {
      const v = state.cfg[it.k] ?? "";
      let input = "";
      if (it.t === "select") input = `<select data-k="${it.k}">${it.o.map(o =>
        `<option ${String(v) === String(o) ? "selected" : ""}>${o}</option>`).join("")}</select>`;
      else if (it.t === "textarea") input = `<textarea data-k="${it.k}" rows="3">${esc(v)}</textarea>`;
      else if (it.t === "check") input = `<input type="checkbox" data-k="${it.k}" ${v ? "checked" : ""}>`;
      else if (it.t === "password") input = `<input type="password" data-k="${it.k}" value="${esc(v)}">`;
      else input = `<input data-k="${it.k}" value="${esc(v)}">`;
      return `<div class="setRow"><span>${it.l}</span>${input}</div>
        ${it.h ? `<div class="setHint">${esc(it.h)}</div>` : ""}`;
    }).join("")}</div>`).join("");
}

async function saveSettings() {
  const patch = {};
  $$("#setBody [data-k]").forEach(el => {
    patch[el.dataset.k] = el.type === "checkbox" ? el.checked : el.value;
  });
  try {
    state.cfg = await api("/api/config", { method: "PUT", body: JSON.stringify({ patch }) });
    toast("设置已保存（API Key 存在 data/secrets.json）", "ok");
    closeModal(); loadEnv();
  } catch (e) { toast("保存失败：" + e.message, "err"); }
}

function renderEnvModal() {
  const e = state.env;
  const b = (v) => v ? '<span style="color:var(--ok)">就绪</span>' : '<span style="color:var(--err)">缺失</span>';
  const st = e.tools?.see_through || {};
  $("#envBody").innerHTML = `<table class="envTable">
    <tr><td>Python</td><td>${esc(e.python?.version)}<br><code>${esc(e.python?.exec)}</code></td></tr>
    <tr><td>GPU</td><td>${e.gpu?.available ? `${esc(e.gpu.name)} · ${e.gpu.vram_gb}GB` : "未探测到 NVIDIA GPU"}</td></tr>
    <tr><td>推荐分层参数</td><td>${esc(e.suggest_decomp_precision?.note || "-")}</td></tr>
    <tr><td>see-through</td><td>${b(st.ok)} ${esc(st.note || "")}
      ${st.marigold_batch_patch === false ? '<br><span style="color:var(--err)">⚠ 缺少 Marigold 分批补丁（L2D_DEPTH_BATCH），8GB 显存会 OOM</span>' : ""}
      <br><code>${esc(st.path || "未配置")}</code></td></tr>
    <tr><td>image2live2d</td><td>${b(e.tools?.image2live2d?.ok)} ${esc(e.tools?.image2live2d?.note || "")}
      <br><code>${esc(e.tools?.image2live2d?.path || "未配置")}</code></td></tr>
    <tr><td>Python 依赖</td><td>rembg ${b(e.deps?.rembg)} · psd-tools ${b(e.deps?.psd_tools)} ·
      pillow ${b(e.deps?.PIL)} · torch ${b(e.deps?.torch)}</td></tr>
    <tr><td>网页预览依赖</td><td>${(e.vendor?.items || []).map(i =>
      `${b(i.ok)} ${esc(i.name)}`).join("<br>")}</td></tr>
  </table>`;
}

/* ---------------- modal ---------------- */
function openModal(which) {
  $("#modalMask").hidden = false;
  $("#modalSet").hidden = which !== "set";
  $("#modalEnv").hidden = which !== "env";
  $("#modalBone").hidden = which !== "bone";
  $("#modalTex").hidden = which !== "tex";
}
function closeModal() { $("#modalMask").hidden = true; }

/* ---------------- 事件绑定 ---------------- */
function bind() {
  $("#btnCreate").onclick = createTask;
  $("#btnRefresh").onclick = () => { loadTasks(); if (state.current) openTask(state.current); };
  $("#fGenMode").onchange = e =>
    $("#fUploadWrap").classList.toggle("hidden", e.target.value !== "upload");

  $("#btnSettings").onclick = async () => { await loadConfig(); renderSettings(); openModal("set"); };
  $("#btnEnv").onclick = async () => { await loadEnv(); openModal("env"); };
  $("#btnCloseSet").onclick = closeModal;
  $("#btnCloseEnv").onclick = closeModal;
  $("#btnSaveSet").onclick = saveSettings;
  $("#btnReload").onclick = async () => { await loadConfig(); renderSettings(); };
  $("#modalMask").onclick = e => { if (e.target.id === "modalMask") closeModal(); };
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

  $("#btnFetchVendor").onclick = async (ev) => {
    const btn = ev.target; btn.disabled = true; btn.textContent = "下载中…";
    try {
      const r = await api("/api/env/fetch-vendor", { method: "POST" });
      const bad = r.results.filter(x => !x.ok);
      toast(bad.length ? `失败：${bad.map(x => x.name).join(", ")}`
                       : "依赖已下载到本地 vendor/", bad.length ? "err" : "ok");
      await loadEnv(); renderEnvModal();
    } catch (e) { toast("下载失败：" + e.message, "err"); }
    btn.disabled = false; btn.textContent = "下载网页预览依赖";
  };

  $("#btnRunStage").onclick = async () => {
    if (!state.task) return;
    try {
      const r = await api(`/api/tasks/${state.task.id}/run`, {
        method: "POST", body: JSON.stringify({ from_stage: state.sel }) });
      toast(r.queue > 0 ? `已入队（前面还有 ${r.queue} 个）` : "开始重跑", "ok");
    } catch (e) { toast(e.message, "err"); }
  };
  $("#btnReset").onclick = async () => {
    if (!state.task || !confirm("会删除该步及之后的所有产物，确定？")) return;
    try {
      const r = await api(`/api/tasks/${state.task.id}/reset/${state.sel}`, { method: "POST" });
      state.task = r.task; renderPipeline(); renderDetail();
    } catch (e) { toast(e.message, "err"); }
  };
  $("#btnCancel").onclick = async () => {
    if (!state.task) return;
    try {
      await api(`/api/tasks/${state.task.id}/cancel`, { method: "POST" });
      toast("已请求取消，正在跑的子进程会一并终止", "ok");
      await openTask(state.task.id);
    } catch (e) { toast("取消失败：" + e.message, "err"); }
  };
  $("#btnDelete").onclick = async () => {
    if (!state.task || !confirm("删除该任务及其全部产物？不可恢复。")) return;
    const id = state.task.id;
    try {
      await api(`/api/tasks/${id}`, { method: "DELETE" });
      state.current = null; state.task = null;
      await loadTasks();
      if (state.tasks.length) openTask(state.tasks[0].id);
      else { renderPipeline(); renderDetail(); $("#logBox").innerHTML = ""; }
      toast("任务已删除", "ok");
    } catch (e) { toast("删除失败：" + e.message, "err"); }
  };
  $("#overFile").onchange = async (e) => {
    const f = e.target.files?.[0];
    if (!f || !state.task) return;
    const fd = new FormData(); fd.append("file", f);
    try {
      const r = await fetch(`/api/tasks/${state.task.id}/input/${state.sel}`,
        { method: "POST", body: fd });
      // 服务端会说明为什么拒收（比如第 4 步只收 .moc3 / 模型包 zip），
      // 不看状态码的话这些提示会被吞掉，只剩一句「上传失败」
      if (!r.ok) throw new Error((await r.text()).slice(0, 200));
      await openTask(state.task.id); toast("已接管该阶段", "ok");
    } catch (err) { toast("上传失败：" + err.message, "err"); }
    e.target.value = "";
  };

  $("#logLevel").onchange = e => { state.logFilter = e.target.value; renderLogs(); };
  $("#btnClearLog").onclick = () => { if (state.task) { state.task.logs = []; renderLogs(); } };

  // 手动滑杆写进 poseOverride，真正生效在 animTick（见上）
  $("#ax").oninput = e => { poseOverride.set("ParamAngleX", +e.target.value); };
  $("#ay").oninput = e => { poseOverride.set("ParamAngleY", +e.target.value); };
  $("#ax").ondblclick = e => { e.target.value = 0; poseOverride.delete("ParamAngleX"); };
  $("#ay").ondblclick = e => { e.target.value = 0; poseOverride.delete("ParamAngleY"); };
  $("#btnIdle").onclick = async () => {
    setPlaying(false);
    poseOverride.clear();
    $("#ax").value = 0; $("#ay").value = 0;
    try { await l2dModel?.motion("Idle", 0, 3); } catch (e) {}
  };
  $("#btnLayerReset").onclick = resetLayers;
  $("#btnOpenModel").onclick = () => {
    const j = state.task?.stages?.preview?.artifacts?.model_json;
    if (j) window.open(fileUrl(j), "_blank");
  };
  $("#btnAnim").onclick = () => setTab("anim");
  $$(".wbTab").forEach(b => b.onclick = () => setTab(b.dataset.tab));

  // 自定义骨骼弹窗
  $("#btnAddBone").onclick = () => {
    if (!l2dModel) { toast("先完成第 5 步加载模型", "err"); return; }
    openBoneModal(null);
  };
  $("#btnBoneOk").onclick = saveBoneForm;
  $("#btnBoneDelete").onclick = deleteBoneForm;
  $("#btnBoneClose").onclick = closeModal;

  // 图片编辑器
  $$(".ttool").forEach(b => b.onclick = () => setTexTool(b.dataset.t));
  $("#btnTexUndo").onclick = undoTex;
  $("#btnTexSave").onclick = saveTexture;
  $("#btnTexClose").onclick = closeModal;
  $("#texReplace").onchange = (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (f) replaceTexture(f);
  };
  const tc = $("#texCanvas");
  tc.addEventListener("pointerdown", texDown);
  tc.addEventListener("pointermove", texMove);
  tc.addEventListener("pointerup", texUp);
  tc.addEventListener("pointercancel", texUp);

  // 配件上传
  $("#accFile").onchange = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (f) await addAccessoryFromFile(f, f.name.replace(/\.[^.]+$/, ""));
  };
  bindAnimPanel();

  $("#btnExport").onclick = async () => {
    if (!state.task) return;
    const btn = $("#btnExport"); btn.disabled = true; btn.textContent = "打包中…";
    try {
      const r = await api(`/api/tasks/${state.task.id}/export?include_player=true`);
      const a = document.createElement("a");
      a.href = r.url; a.download = r.name || "live2d.zip";
      document.body.appendChild(a); a.click(); a.remove();
      toast(`已导出 ${r.files} 个文件（含离线播放器 player.html）`, "ok");
    } catch (e) { toast("导出失败：" + e.message, "err"); }
    btn.disabled = false; btn.textContent = "导出模型包";
  };

  // 排队/运行中低频轮询兜底（WS 断线时也能看到进度）
  setInterval(() => {
    if (state.current && ["running", "queued", "idle"].includes(state.task?.status))
      api(`/api/tasks/${state.current}`).then(d => {
        state.task = d; renderPipeline(); renderDetail(); renderLogs(); maybeLoadModel();
      }).catch(() => {});
  }, 5000);
}

/* ---------------- boot ---------------- */
(async function boot() {
  bind();
  await Promise.all([loadEnv(), loadConfig(), loadTasks()]);
  if (state.tasks.length) openTask(state.tasks[0].id);
  else renderPipeline();
})();

})();
