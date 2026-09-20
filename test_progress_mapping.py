# -*- coding: utf-8 -*-
"""验证 run_cmd 的实时转发与分层进度换算。

用子进程完全复刻 see-through 的输出风格：进度条用 \\r 原地刷新、
阶段标记用 print 换行。校验：进度单调递增到 99%、日志不被 \\r 刷新
刷爆、普通阶段标记行不被吞。重构进度相关代码后跑一下。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server.progress import make_decompose_progress  # noqa: E402
from server.runner import run_cmd                    # noqa: E402


class FakeTask:
    def __init__(self):
        self.lines = []
        self.progs = []

    def log(self, msg, level="info", stage=None):
        self.lines.append((level, msg))

    def stage_progress(self, sid, pct, msg=""):
        self.progs.append(int(pct))


# 子进程：完全复刻 see-through 的输出风格
CHILD = r'''
import sys, time

def bar(cur, tot, t):
    sys.stderr.write(
        "\r%3d%%|%s| %d/%d [%s<00:00, 38.78s/it]" % (
            int(cur * 100 / tot), "#" * (cur * 20 // tot), cur, tot, t))
    sys.stderr.flush()

print("Building LayerDiff3D pipeline...", flush=True)
for i in range(1, 6):
    bar(i, 5, "00:0%d" % i); time.sleep(0.01)
sys.stderr.write("\n")

print("Running LayerDiff3D (body + head)...", flush=True)
for _p in range(2):                       # body + head 两遍
    for i in range(1, 31):
        bar(i, 30, "00:%02d" % i); time.sleep(0.004)
    sys.stderr.write("\n")
print("  LayerDiff3D done in 10.0s", flush=True)

print("Building Marigold depth pipeline...", flush=True)
print("Running Marigold depth...", flush=True)
for _c in range(8):                       # 8 段
    for i in range(1, 5):
        bar(i, 4, "00:%02d" % i); time.sleep(0.004)
    sys.stderr.write("\n")
print("  Marigold done in 3.0s", flush=True)

print("Running PSD assembly...", flush=True)
print("psd saved to workspace/layerdiff_output\\clean.psd", flush=True)
print("Stats saved to workspace/layerdiff_output\\clean\\stats.json", flush=True)
'''


def main():
    task = FakeTask()
    rc = asyncio.run(run_cmd(
        task,
        [sys.executable, "-c", CHILD],
        stage="decompose",
        timeout=120,
        on_line=make_decompose_progress(),
    ))
    print("exit code:", rc)
    print()
    print("=== 落下来的日志（%d 条）===" % len(task.lines))
    for lv, m in task.lines:
        print("  [%s] %s" % (lv, m[:78]))
    print()
    print("=== 进度序列（%d 次跃迁）===" % len(task.progs))
    print(" ", task.progs)
    print()
    mono = all(task.progs[i] <= task.progs[i + 1] for i in range(len(task.progs) - 1))
    print("单调递增 :", mono)
    print("最终进度 :", task.progs[-1] if task.progs else None)

    ok = (
        rc == 0
        and mono
        and bool(task.progs)
        and task.progs[-1] == 99
        and len(task.progs) < 150         # 没把每次 \r 刷新都写成日志
        and any("LayerDiff3D done" in m for _, m in task.lines)
        and any("Running LayerDiff3D" in m for _, m in task.lines)
    )
    print()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
