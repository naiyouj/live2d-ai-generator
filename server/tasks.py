"""任务状态机、磁盘元数据、日志广播、全局执行队列。

设计要点：
- task.json 落盘在 workspace/<任务号>/，五阶段状态与产物路径都在里面；
  schema 与 v1 保持一致，旧任务目录重启后原样可见。
- JobQueue 是全局单工人队列：8GB 显存同时只允许一条流水线在跑，
  后提交的任务排队（status="queued"），排队中可随时取消。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

# 阶段定义：顺序即流水线顺序
STAGES: List[Dict[str, str]] = [
    {"id": "generate", "name": "AI 生图", "desc": "文生图或直接上传立绘"},
    {"id": "preprocess", "name": "预处理", "desc": "去背景、裁切居中"},
    {"id": "decompose", "name": "AI 分层", "desc": "拆成 20+ 语义 RGBA 图层"},
    {"id": "rig", "name": "AI 绑骨", "desc": "生成 mesh / 物理 / 动作"},
    {"id": "preview", "name": "预览导出", "desc": "打包模型并在网页驱动"},
]

STAGE_IDS = [s["id"] for s in STAGES]


def _blank_stage(sid: str) -> Dict[str, Any]:
    return {
        "id": sid,
        "status": "pending",   # pending | running | done | error | skipped
        "progress": 0,
        "message": "",
        "started_at": None,
        "finished_at": None,
        "outputs": [],
        "artifacts": {},       # 语义键 -> 相对路径
    }


class Task:
    def __init__(self, task_id: str, name: str = "", params: Optional[Dict[str, Any]] = None):
        self.id = task_id
        self.name = name or f"任务 {task_id[:8]}"
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.params: Dict[str, Any] = params or {}
        # 本次运行的起始阶段，只活在内存里（不落盘）：阶段实现靠它区分
        # 「续跑」和「显式重跑」——重跑必须真执行，不能把旧产物当结果交回去
        self.rerun_from: Optional[str] = None
        self.status = "idle"   # idle | queued | running | done | error | cancelled
        self.stages: Dict[str, Dict[str, Any]] = {s["id"]: _blank_stage(s["id"]) for s in STAGES}
        self.logs: List[Dict[str, Any]] = []
        self.dir = config.WORKSPACE_DIR / task_id
        self.error: Optional[str] = None
        self._subs: List[asyncio.Queue] = []

    # ---------- 目录 ----------
    def stage_dir(self, sid: str) -> Path:
        p = self.dir / sid
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ensure_dirs(self) -> None:
        for sid in STAGE_IDS:
            self.stage_dir(sid)

    # ---------- 日志 ----------
    def log(self, msg: str, level: str = "info", stage: Optional[str] = None) -> None:
        entry = {"t": time.time(), "level": level, "stage": stage, "msg": msg}
        self.logs.append(entry)
        if len(self.logs) > 4000:
            self.logs = self.logs[-3000:]
        self.updated_at = time.time()
        self._broadcast({"type": "log", "task": self.id, "data": entry})

    # ---------- 阶段状态 ----------
    def stage_start(self, sid: str, msg: str = "") -> None:
        s = self.stages[sid]
        s.update(status="running", progress=1, message=msg,
                 started_at=time.time(), finished_at=None)
        self.status = "running"
        self.updated_at = time.time()
        self._broadcast({"type": "stage", "task": self.id, "data": dict(s)})

    def stage_progress(self, sid: str, pct: int, msg: str = "") -> None:
        s = self.stages[sid]
        s["progress"] = max(s.get("progress", 0), int(pct))
        if msg:
            s["message"] = msg
        self.updated_at = time.time()
        self._broadcast({"type": "stage", "task": self.id, "data": dict(s)})

    def stage_done(self, sid: str, msg: str = "", artifacts: Optional[Dict[str, str]] = None) -> None:
        s = self.stages[sid]
        s.update(status="done", progress=100, message=msg, finished_at=time.time())
        if artifacts:
            s["artifacts"].update(artifacts)
        self._scan_outputs(sid)
        if all(self.stages[x]["status"] in ("done", "skipped") for x in STAGE_IDS):
            self.status = "done"
        self.updated_at = time.time()
        self._broadcast({"type": "stage", "task": self.id, "data": dict(s)})
        self.save()

    def stage_error(self, sid: str, msg: str) -> None:
        s = self.stages[sid]
        s.update(status="error", message=msg, finished_at=time.time())
        self.status = "error"
        self.error = msg
        self.updated_at = time.time()
        self._broadcast({"type": "stage", "task": self.id, "data": dict(s)})
        self.save()

    def stage_skip(self, sid: str, msg: str = "已跳过") -> None:
        s = self.stages[sid]
        s.update(status="skipped", message=msg, progress=100, finished_at=time.time())
        self.updated_at = time.time()
        self._broadcast({"type": "stage", "task": self.id, "data": dict(s)})

    # ---------- 产物扫描 ----------
    _IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

    def _scan_outputs(self, sid: str) -> None:
        d = self.stage_dir(sid)
        outs = []
        for p in sorted(d.rglob("*")):
            if not p.is_file() or p.name == "task.json" or p.name.startswith("."):
                continue
            rel = p.relative_to(self.dir).as_posix()
            outs.append({
                "name": p.name,
                "path": rel,
                "size": p.stat().st_size,
                "is_image": p.suffix.lower() in self._IMG_EXT,
            })
        self.stages[sid]["outputs"] = outs

    def rel_path(self, abs_path: Path) -> str:
        try:
            return Path(abs_path).resolve().relative_to(self.dir.resolve()).as_posix()
        except Exception:
            return str(abs_path)

    # ---------- 序列化 ----------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "error": self.error,
            "params": self.params,
            "stages": self.stages,
            "logs": self.logs[-500:],
        }

    def summary(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "error": self.error,
            "stages": {k: {"status": v["status"], "progress": v["progress"],
                           "message": v["message"]} for k, v in self.stages.items()},
        }

    def save(self) -> None:
        try:
            self.ensure_dirs()
            data = self.to_dict()
            data.pop("logs", None)
            tmp = self.dir / "task.json.tmp"
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.dir / "task.json")
        except Exception:
            pass

    # ---------- 订阅 ----------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subs.remove(q)
        except ValueError:
            pass

    def _broadcast(self, payload: Dict[str, Any]) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(payload)
            except Exception:
                self.unsubscribe(q)


class TaskManager:
    def __init__(self) -> None:
        self.tasks: Dict[str, Task] = {}
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not config.WORKSPACE_DIR.exists():
            return
        for d in config.WORKSPACE_DIR.iterdir():
            meta = d / "task.json"
            if not (d.is_dir() and meta.exists()):
                continue
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except Exception:
                continue
            t = Task(d.name, data.get("name", d.name), data.get("params") or {})
            t.created_at = data.get("created_at", t.created_at)
            t.status = data.get("status", "idle")
            # 上次进程退出时还在跑的任务不可能有结果了，回落为 idle
            if t.status in ("running", "queued"):
                t.status = "idle"
            t.error = data.get("error")
            for sid, st in (data.get("stages") or {}).items():
                if sid in t.stages:
                    t.stages[sid].update({k: v for k, v in st.items() if k != "outputs"})
            for sid in STAGE_IDS:
                t._scan_outputs(sid)
            self.tasks[t.id] = t

    def create(self, name: str = "", params: Optional[Dict[str, Any]] = None) -> Task:
        tid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        t = Task(tid, name, params)
        t.ensure_dirs()
        self.tasks[tid] = t
        t.save()
        return t

    def get(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def list(self) -> List[Dict[str, Any]]:
        return sorted((t.summary() for t in self.tasks.values()),
                      key=lambda x: x["created_at"], reverse=True)

    def remove(self, task_id: str) -> bool:
        t = self.tasks.pop(task_id, None)
        if not t:
            return False
        import shutil
        shutil.rmtree(t.dir, ignore_errors=True)
        return True


class JobBusyError(RuntimeError):
    """任务已在队列或运行中。"""


class JobQueue:
    """全局任务队列：同一时刻最多一条流水线在执行。

    分层步骤要独占 8GB 显存数分钟到一小时，两条流水线并发必然 OOM，
    所以新任务一律排队，跑完一个再取下一个。排队中的任务可取消。
    """

    def __init__(self) -> None:
        self._queue: deque = deque()          # (task_id, from_stage)
        self._running: Dict[str, asyncio.Task] = {}
        self._wakeup = asyncio.Event()
        self._worker: Optional[asyncio.Task] = None

    # ---- 对外 ----
    def submit(self, task: Task, from_stage: Optional[str] = None) -> int:
        """入队，返回前面还有多少个任务：0 = 马上开跑，n = 前面压着 n 个。"""
        if self.position(task.id) is not None:
            raise JobBusyError("该任务已在队列或运行中")
        ahead = len(self._running) + len(self._queue)
        self._queue.append((task.id, from_stage))
        task.status = "queued"
        task.error = None
        task.save()
        self._ensure_worker()
        self._wakeup.set()
        return ahead

    def position(self, task_id: str) -> Optional[int]:
        if task_id in self._running:
            return 0
        ids = [tid for tid, _ in self._queue]
        if task_id in ids:
            return 1 + ids.index(task_id)
        return None

    def cancel(self, task_id: str) -> None:
        """取消排队/运行中的任务。"""
        self._queue = deque(x for x in self._queue if x[0] != task_id)
        tk = self._running.get(task_id)
        if tk and not tk.done():
            tk.cancel()

    # ---- 内部 ----
    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        while True:
            await self._wakeup.wait()
            self._wakeup.clear()
            while self._queue:
                tid, from_stage = self._queue.popleft()
                task = manager.get(tid)
                if task is None:
                    continue
                tk = asyncio.create_task(self._run_one(task, from_stage))
                self._running[tid] = tk
                try:
                    await tk
                except asyncio.CancelledError:
                    pass
                finally:
                    self._running.pop(tid, None)

    async def _run_one(self, task: Task, from_stage: Optional[str]) -> None:
        from . import pipeline   # 延迟导入，避免 tasks <-> pipeline 循环

        try:
            await pipeline.run_pipeline(task, from_stage)
        except asyncio.CancelledError:
            task.log("任务已取消", "warn")
        except Exception as e:
            task.status = "error"
            task.error = str(e)
            task.log(f"流水线异常：{e}", "error")
        finally:
            task.save()
            task._broadcast({"type": "done", "task": task.id, "data": task.status})


manager = TaskManager()
jobs = JobQueue()
