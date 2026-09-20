"""流水线编排：按序执行五阶段，支持跳过已完成、从指定阶段重跑。"""

from __future__ import annotations

import asyncio
from typing import Optional

from .stages import stage_decompose, stage_generate, stage_preprocess, stage_preview, stage_rig
from .tasks import STAGE_IDS, Task

STAGE_FUNCS = {
    "generate": stage_generate,
    "preprocess": stage_preprocess,
    "decompose": stage_decompose,
    "rig": stage_rig,
    "preview": stage_preview,
}


async def run_pipeline(task: Task, from_stage: Optional[str] = None) -> None:
    """按序执行；单阶段失败中止后续（保留已完成产物，可从失败阶段重跑）。"""
    order = list(STAGE_IDS)
    if from_stage and from_stage in order:
        order = order[order.index(from_stage):]

    # 告诉各阶段本次是「从哪一步开始跑的」：显式重跑的阶段必须真执行，
    # 不能拿磁盘上的旧产物当结果（生图阶段尤其明显）
    task.rerun_from = from_stage

    for sid in order:
        if task.status == "cancelled":
            task.log("任务已取消", "warn", sid)
            return
        if task.stages[sid]["status"] == "done" and task.params.get("skip_done"):
            task.log(f"{sid} 已完成，跳过", "info", sid)
            continue
        try:
            await STAGE_FUNCS[sid](task)
        except asyncio.CancelledError:
            task.stage_error(sid, "已取消")
            raise
        except Exception as e:
            task.log(str(e), "error", sid)
            task.stage_error(sid, str(e))
            return

    if task.status != "error":
        task.status = "done"
        task.save()
