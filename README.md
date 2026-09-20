# Live2D AI 生成器 v2

把 **AI 生图 → 一张图 → 可动 Live2D 模型** 的完整流程做成本地 Web 应用，全部在本机运行。

```
步骤1 AI生图  →  步骤2 预处理  →  步骤3 AI分层  →  步骤4 AI绑骨  →  步骤5 预览导出
   立绘PNG        去背景裁切      20+ RGBA图层      mesh/物理/动作     .moc3 模型包
```

## 功能特性

- **全流程本地化**：生图 → 分层 → 绑骨 → 导出全部在本机完成，图片不上传任何外部服务
- **可视化流水线**：浏览器控制台（`http://127.0.0.1:7800`），五步进度实时展示
- **全局任务队列**：同一时刻只跑一条流水线，8GB 显存也不会被打架
- **每一关都能手动接管**：任意一步可上传现成产物（立绘 PNG / PSD / .moc3）跳过该步
- **API Key 隔离**：密钥单独存 `data/secrets.json`，备份打包自动排除
- **断点续跑**：已完成步骤自动跳过，支持「从此步重跑」

v2 是整体重写版：代码重组为 `server/` 包、全局任务队列（同一时刻只跑一条
流水线，8GB 显存不会被打架）、配置类型化、**API Key 从 config.json 拆到
`data/secrets.json`**（备份打包自动排除）。对外功能与 v1 一致，旧任务目录
兼容。

---

## 快速开始

**双击 `启动.bat`**，浏览器自动打开 `http://127.0.0.1:7800`。

| 方式 | 操作 |
|---|---|
| **`启动.bat`** | 日常启服务 |
| `安装环境.bat` | 装/补依赖（venv 已装好，一般不用） |
| `下载外部工具.bat` | 下载 see-through / image2live2d 两个仓库并自动套上本地补丁，顺带下网页预览依赖（约 150MB；**从 GitHub 拉下来的代码先跑这个**） |
| `下载分层模型.bat` | 预下载步骤3的三组模型（约 12GB，只跑一次，自动跳过已下好的） |
| `备份打包.bat` | 打整个项目成 zip，**自动排除 API Key**（`--no-venv` 可大幅减小体积） |

所有 bat 都走项目里的 `.venv`，不碰系统 Python。

### 运行环境（本机现状）

- Python 解释器：`C:\Python313`（3.13.9，用户级安装），`.venv` 的
  `pyvenv.cfg` 指向它。之前的 venv 基础解释器（workbuddy 托管版）已被删除，
  2026-09-15 重装并重指，site-packages 无损。
- 显卡：RTX 2070 8GB，torch 2.8.0+cu126，CUDA 可用。

### 闪退 / 报错先看这里

`启动.bat` 出错时会 `pause` 等你按键。如果看到 `venv not found`：

```bat
python -m venv .venv
.venv\Scripts\python.exe setup_env.py
```

> **改 bat 的注意事项**：bat 一律 **纯 ASCII + CRLF**（用 `tools` 里或任何
> 脚本以二进制写入）。UTF-8 无 BOM 会乱码，LF 会让相邻语句粘连，
> VS Code 存成 UTF-8 是老坑。

### 端口冲突

```
.venv\Scripts\python.exe run.py --port 8080
.venv\Scripts\python.exe run.py --host 0.0.0.0 --port 8080   # 局域网可访问
```

---

## 首次使用（新机器）

> 前提：装好 [git 或直接用 GitHub Desktop 拉代码](https://github.com/)，
> 装好 Python 3.13（`python -m venv .venv` 要用）。代码本体从 GitHub
> `git clone` 下来即可，大文件都不在仓库里，按下面步骤自动补齐。

1. **`安装环境.bat`**（只做一次）：自动探测显卡驱动选对应 CUDA 版的
   PyTorch，装 see-through 推理依赖、image2live2d、rembg、Web 控制台依赖，
   写 `data/config.json`。下 3~5GB，失败了直接重跑，会跳过已装的。
   跑完看验证报告里的 `torch 2.8.0+cu126` / `cuda True` 两行。
2. **`下载外部工具.bat`**：按 pinned 提交号下载 see-through / image2live2d
   两个仓库到 `tools/`，自动覆盖本地补丁（`patches/`），顺带把 Cubism Core /
   PixiJS / pixi-live2d-display 下到 `server/web/vendor/`。无需装 git。
3. **`下载分层模型.bat`**（要跑步骤3时）：预下三组 HF 模型，约 12GB。
4. **设置 → 生图** 配置生图接口，二选一：
   - 在线/本地 API：OpenAI 兼容端点（`https://xxx/v1`）+ Key + 模型名
   - ComfyUI：地址 + workflow 的 API format JSON（自动替换提示词与 seed）
   - **上传本地图片**：最简单，跳过生图环节

两个外部工具仓库**不进 git**（体积大 + 尊重上游），由 `下载外部工具.bat`
按 `patches/*/HEAD.txt` 记录的提交号自动拉取并套补丁：

| 工具 | 位置 | 对应步骤 |
|---|---|---|
| see-through | `tools\see-through` | 步骤3 分层 |
| image2live2d | `tools\image2live2d` | 步骤4 绑骨 |

## 生图环节的硬约束

这是整条链路**唯一需要人工把关**的地方，后面四步全自动：

- **A-pose** —— 双臂自然下垂且略微离开躯干（动态姿势会让头/发块脱离身体）
- **背景纯色** —— 花哨背景会让分层模型乱套
- **全身 + 正面 + 单人** —— 半身、侧身、多人都不行

「正向后缀」「负向提示」默认已配好这三条，别删改。

## 显存分档

步骤3（分层）是唯一显存瓶颈，程序按显存自动推荐，可手动覆盖：

| 显存 | 精度 | 分辨率 | group_offload |
|---|---|---|---|
| ≥16GB | bf16 | 1280 | 关 |
| 11–15GB | bf16 | 1024 | 开 |
| 8–11GB | NF4 量化 | 1024 | 强制关（与 bnb 4bit 冲突） |
| 无 NVIDIA GPU | — | — | 建议云 GPU 跑分层，再上传 PSD 接管第 4 步 |

8GB 卡跑 1024 分层实测 **约 1 小时**；768 分辨率约减半。任务队列同时只跑
一条流水线，后提交的自动排队。

## 每一关都能手动接管

点流水线上任意一步，右上角 **「上传接管」**：

- 步骤1 —— 传你自己的立绘 PNG
- 步骤3 —— 传别人/云上跑好的 `layers.psd`
- 步骤4 —— 传现成 `.moc3`，或把整个模型目录（`.moc3` + `model3.json` +
  带贴图的 `textures/`）打成 **zip** 传上来。预览要靠 `model3.json` 找模型、
  靠贴图渲染，只传一个 `.moc3` 是驱动不起来的

「从此步重跑」只重跑后半段，前面的产物保留；在第 1 步点它 = 真的重画一张
（生图模式会重新出图，upload 模式无图可生、仍沿用你传的那张）。

## 编辑工作台（动画 / 图层 子页）

第 5 步完成后，预览下方是 **带子页签的编辑工作台**：「动画编辑」与
「图层管理」两个子页切换显示，不用上下滚动找面板；画布始终可见，
骨骼手柄在「动画编辑」页上直接拖。

### 动画编辑（Blender 式骨骼 + 时间轴）

- **骨骼手柄**：moc3 没有骨架，这里按参数组做了 9 个可拖拽手柄
  （头/眼/眉/嘴/身/双臂/前后发），锚定在对应部件网格的质心上，
  拖动即写参数（X 向拖写横摆通道、Y 向拖写纵向通道），实时反映到模型。
- **自定义骨骼**：「＋骨骼」可以给内置手柄覆盖不到的部位（裙摆、
  飘带、尾巴…）建新手柄——任选一个网格当锚点、绑任意参数通道
  （轴向 + 灵敏度），定义存进模型包 `custom_bones.json`，导出后仍在；
  骨骼行的「改」「删」可随时编辑。
- **配件**：「＋图片」上传 PNG（或在图层页圈选剥离生成），
  绑到任意骨骼上跟随移动：跟随权重（1 = 完全贴住骨骼，0 = 钉在画布
  中心）、缩放、旋转、偏移、模型前/后层级都可在列表里调，画布上直接
  拖配件调偏移。数据存 `accessories/accessories.json`，导出的
  player.html 会内嵌配件并复刻跟随逻辑。
- **打帧**：拖好后按 **K**（或「K 打帧」）给选中骨骼打一帧；
  **K! 全部** 给所有动过的骨骼打帧；勾选 **自动打帧** 则每次拖完自动打。
  快捷键：`Space` 播放/暂停，`K` 打帧，`Delete` 删播放头处的帧。
- **dope sheet 时间轴**：每个骨骼一行，菱形=关键帧。拖动改时间、
  单击切换缓动（线性/平滑/阶梯）、右键删除；时间尺上拖动 = 移动播放头。
- **保存动作**：起个名字点「保存动作」，编成标准 `motion3.json`
  写进模型包并登记到 `model3.json` 的 Custom 组（Cubism Editor 也能认），
  动作库里点 ▶ 随时回放，可删除。
- **导出模型包**：一键打包 `moc3 + 贴图 + model3.json + 全部动画 +
  配件 + 自定义骨骼`，并附带单文件 `player.html`（模型与配件内嵌成
  data URL），双击就能在浏览器里驱动模型和动画，不需要起服务。

### 待机动作自动去 Z 轴

自动生成的待机动作带 `ParamAngleZ / ParamBodyAngleZ`（面内旋转）曲线，
AI 网格做面内旋转会整体扭曲。预览打包时自动剔除（`server/motutil.py`），
前端加载模型前也会幂等补一刀，待机只剩 X/Y 摆动。

## 图层管理（含图片编辑）

第 5 步完成后，图层按 **部件分组** 展示成卡片网格：组头有贴图缩略图、
cdi3 里的可读部件名（Hair Back / Clothing…）和网格数，网格行带
UV 裁剪缩略图，支持 ▲▼ 微调与拖拽排序；「隐藏」按钮关闭整个部件
的不透明度（Cubism 核心没有单网格显隐接口）。「还原」恢复出厂顺序。

组头的 **「✎ 图」** 打开图片编辑器，直接修 AI 没抠干净的原图：

- **橡皮擦 / 圈选擦除**：把杂边、残留背景擦成透明（可撤销，保存写回贴图）；
- **圈选剥离成配件**：在饰品、道具上圈一圈，自动剪成独立配件 PNG
  并进配件列表，去动画页绑骨骼即可让它跟着动；
- **替换整图**：用本地图片整张替换该贴图。
  保存后模型自动热重载。

## 目录说明

```
server/          后端（FastAPI）+ 前端页面
  config.py      类型化配置；密钥在 data/secrets.json，与 config.json 分离
  tasks.py       任务状态机 + 全局执行队列（GPU 串行化）
  runner.py      子进程执行器（\r/\n 双切行 + 进度条限流）
  progress.py    see-through 输出 → 界面进度的换算
  stages.py      五个阶段的实现
  pipeline.py    编排（跳过已完成 / 从指定阶段重跑）
  envcheck.py    环境自检（含 see-through Marigold 分批补丁检测）
  api.py         全部 HTTP/WS 接口（动作/贴图/配件/自定义骨骼/导出）
  motutil.py     待机动作剔除 Z 轴曲线（预览打包与手动修正共用）
  player.py      导出包里的单文件离线播放器生成（含配件跟随）
  web/           index.html / app.css / app.js / vendor(预览依赖，git 忽略)
patches/         外部工具的本地补丁快照（整文件覆盖层 + changes.diff +
                 HEAD.txt 提交号），下载外部工具.bat 用它自动套补丁
tools/           fetch_tools / download_models / make_backup 等自有脚本 +
                 两个外部仓库（git 忽略，bat 自动拉取）
workspace/       任务产物，每个任务一个目录，按 stage 分子目录（git 忽略）
data/            config.json（入库）+ secrets.json（API Key，git 忽略）
```

### git 仓库里有什么、没什么

- **在仓库里**：全部自有代码（`server/`、`tools/*.py`、根目录 py + bat）、
  `patches/` 补丁快照、`data/config.json`。
- **不在仓库里**（自动重建/下载）：`.venv`（安装环境.bat）、
  `tools/see-through`、`tools/image2live2d`（下载外部工具.bat）、
  `server/web/vendor`（下载外部工具.bat 或环境自检按钮）、`workspace/`
  （任务产物）、`logs/`、`data/secrets.json`（**API Key，永远不进 git**）。

## API

自带 OpenAPI 文档：`http://127.0.0.1:7800/docs`

取消与删除任务（`POST /api/tasks/{id}/cancel`、`DELETE /api/tasks/{id}`）目前
界面上没有按钮，要从 `/docs` 调。取消会连带 `taskkill /T` 掉正在跑的子进程 ——
否则那个占着显存的推理进程会活下来，队列里下一个任务必然 OOM。

## 测试

```
.venv\Scripts\python.exe smoke_test.py            # 接口冒烟（不碰真实配置）
.venv\Scripts\python.exe test_progress_mapping.py # 进度映射回放
```

## 注意事项

- `.moc3` 是 Live2D 的闭源二进制格式，程序生成的模型靠社区逆向实现。
  自己玩没问题，**商用前务必在 Cubism Editor 里过一遍再导出**。
- `tools/see-through` 的 `inference_psd_quantized.py` 带有本地补丁
  （Marigold 分批推理，`L2D_DEPTH_BATCH`）。补丁以整文件快照存在
  `patches/see-through/overlay/`，`下载外部工具.bat` 会自动套上。
  **更新该仓库后要重新导出补丁**（重跑补丁快照脚本、更新 `HEAD.txt` 的
  提交号），环境自检会检测补丁是否在位。
- `tools/image2live2d` 的 `src/image2live2d/__main__.py` 带有本地补丁：
  CLI 的 `--live2d` 默认只输出 JSON 模型包（model3/physics3/motion3/cdi3），
  不写 `.moc3` 二进制。补丁注入了 `native_moc_writer`（从零生成 `.moc3`），
  服务端第 4 步才拿得到 `.moc3` 产物。补丁快照（含 `_head.bin`、
  `tests/test_neck_zorder.py` 两个新增文件）在 `patches/image2live2d/`，
  `下载外部工具.bat` 自动套上。**更新该仓库要重新导出补丁**（在
  `Live2DEmitter(...)` 处补 `moc_writer=native_moc_writer` 并 import
  `from .backends.live2d.moc3_emit import native_moc_writer`）。
- API Key 明文存在 `data/secrets.json`，打包/分享项目时用
  `备份打包.bat`（自动排除），别手动 zip 全目录。
