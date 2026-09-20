"""异步子进程执行器：stdout/stderr 逐行实时转发到任务日志与进度。

两个关键机制（都是实测踩坑换来的，别删）：

1. **按 \\r 和 \\n 双分隔符切行**。tqdm 进度条用 \\r 原地刷新且结尾不换行，
   如果只按 \\n 切，整条进度历史会一直滞留在管道缓冲里，直到该进度条跑完
   才作为「一行」一次性吐出 —— 41 分钟的 LayerDiff 推理在界面上完全静默，
   看起来就像卡死。

2. **进度条行限流**。切行后每次 \\r 刷新都是独立一行，量会爆炸；用
   _TQDM_RE 识别进度条行，百分比没前进就不落日志（只让它推动进度值）。
   脚本自己 print 的阶段标记行不受限流，照常逐条输出。
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional, Sequence, TYPE_CHECKING

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")           # 终端控制序列
_TQDM_RE = re.compile(r"%\s*\|.*\|\s*\d+\s*/\s*\d+\s*[\[(]")  # tqdm 进度条行

if TYPE_CHECKING:
    from .tasks import Task


def _kill_tree(proc) -> None:
    """终止子进程及其后代，尽力而为，绝不抛异常。

    Windows 上 proc.kill() 只收直接子进程，工具内部再拉起的进程会残留成
    孤儿；taskkill /T 连整棵树一起收，所以自己起的进程走这条路。
    """
    if proc.returncode is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=15)
        else:
            proc.kill()
    except Exception:
        pass
    try:
        proc.kill()      # 兜底：taskkill 不可用时至少收掉直接子进程
    except Exception:
        pass


async def run_cmd(
    task: "Task",
    cmd: Sequence[str],
    cwd: Optional[str] = None,
    env_extra: Optional[dict] = None,
    timeout: Optional[float] = None,
    on_line: Optional[Callable[[str], Optional[int]]] = None,
    stage: Optional[str] = None,
) -> int:
    """执行命令并实时转发输出。返回退出码。"""
    display = " ".join(shlex.quote(str(c)) for c in cmd)
    task.log(f"$ {display}", level="cmd", stage=stage)

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    env["NO_COLOR"] = "1"
    if env_extra:
        env.update({str(k): str(v) for k, v in env_extra.items()})

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        proc = await asyncio.create_subprocess_exec(
            *(str(c) for c in cmd),
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            creationflags=creationflags,
        )
    except FileNotFoundError as e:
        task.log(f"命令不存在：{e}", level="error", stage=stage)
        return 127
    except Exception as e:
        task.log(f"启动失败：{e}", level="error", stage=stage)
        return 126

    async def _pump() -> None:
        assert proc.stdout is not None
        buf = b""
        last_pct: Optional[int] = None
        while True:
            try:
                chunk = await proc.stdout.read(8192)
            except Exception:
                break
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()          # 末段可能被截断，留到下一轮拼接
            for raw in parts:
                line = _ANSI_RE.sub("", raw.decode("utf-8", "replace")).strip()
                if not line:
                    continue
                pct = None
                if on_line:
                    try:
                        pct = on_line(line)
                    except Exception:
                        pct = None

                if _TQDM_RE.search(line):
                    if pct is None:
                        continue       # 与本阶段无关的进度条（如加载权重）
                    if last_pct is not None and pct < last_pct:
                        pct = last_pct  # 进度只前进，忽略回退的重复刷新
                    if pct == last_pct:
                        continue
                    last_pct = pct
                    task.log(line, level="info", stage=stage)
                    if stage:
                        task.stage_progress(stage, min(int(pct), 99))
                    continue

                lvl = "error" if ("Traceback" in line or line.lower().startswith("error")) else "info"
                task.log(line, level=lvl, stage=stage)
                if pct is not None and stage:
                    task.stage_progress(stage, min(int(pct), 99))
        tail = _ANSI_RE.sub("", buf.decode("utf-8", "replace")).strip()
        if tail:
            task.log(tail, level="info", stage=stage)

    try:
        if timeout:
            await asyncio.wait_for(_pump(), timeout=timeout)
            await asyncio.wait_for(proc.wait(), timeout=30)
        else:
            await _pump()
            await proc.wait()
    except asyncio.TimeoutError:
        task.log(f"执行超时（>{timeout}s），终止进程", level="error", stage=stage)
        _kill_tree(proc)
        return 124
    except asyncio.CancelledError:
        # 用户取消任务 / 服务退出走这条路径。CancelledError 继承 BaseException，
        # 下面的 except Exception 拦不住它，所以必须在这里单独收掉子进程 ——
        # 否则那个正在占着显存跑分层的进程会活下来，队列里下一个任务必然 OOM。
        task.log("任务已取消，终止子进程", level="warn", stage=stage)
        _kill_tree(proc)
        raise
    except Exception as e:
        task.log(f"执行异常：{e}", level="error", stage=stage)
        _kill_tree(proc)
        return 1

    rc = proc.returncode or 0
    task.log("命令执行成功" if rc == 0 else f"命令退出码 {rc}",
             level="ok" if rc == 0 else "error", stage=stage)
    return rc
