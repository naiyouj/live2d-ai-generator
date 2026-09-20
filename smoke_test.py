# -*- coding: utf-8 -*-
"""冒烟测试：核心接口跑一遍，不依赖外部工具，不真正跑 GPU 流水线。

用 `with TestClient(...)` 保持事件循环存活，JobQueue 的后台任务才能
跨请求执行。配置读写测试用临时文件，绝不污染真实 data/config.json。
"""
import io
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi.testclient import TestClient  # noqa: E402

from server import config as config_mod  # noqa: E402
from server.main import app  # noqa: E402

fails = []
c = TestClient(app)


def check(name, fn, expect=(200,)):
    try:
        r = fn()
        ok = r.status_code in expect
        print(f"[{'OK ' if ok else 'FAIL'}] {name} -> {r.status_code}")
        if not ok:
            fails.append((name, r.status_code, r.text[:300]))
        return r
    except Exception as e:
        print(f"[FAIL] {name} -> {e}")
        fails.append((name, "EXC", str(e)[:300]))
        return None


# ---------------------------------------------------------------- 基础
check("GET /", lambda: c.get("/"))
check("GET /health", lambda: c.get("/health"))
check("GET /static/app.js", lambda: c.get("/static/app.js"))
check("GET /vendor/pixi.min.js", lambda: c.get("/vendor/pixi.min.js"))

r = check("GET /api/env", lambda: c.get("/api/env"))
if r:
    env = r.json()
    print(f"      gpu={env['gpu']}")
    assert "suggest_decomp_precision" in env

# ---------------------------------------------------------------- 配置
# 指到临时文件，测试类型归一与密钥分离，不碰真实配置
tmp_dir = tempfile.mkdtemp()
config_mod.CONFIG_FILE = Path(tmp_dir) / "config.json"
config_mod.SECRETS_FILE = Path(tmp_dir) / "secrets.json"

r = check("GET /api/config", lambda: c.get("/api/config"))
if r:
    body = r.json()
    print(f"      api_key={body.get('api_key')!r} port={body.get('port')!r} "
          f"steps={body.get('decomp_steps')!r}")
    if body.get("api_key") not in ("", "******"):
        fails.append(("config mask", "LEAK", str(body.get("api_key"))))

r = check("PUT /api/config (字符串类型归一)", lambda: c.put("/api/config", json={
    "patch": {"port": "7800", "decomp_steps": "45",
              "decomp_group_offload": "true", "api_key": "sk-test-secret"}}))
r = check("GET /api/config (验证)", lambda: c.get("/api/config"))
if r:
    body = r.json()
    if not (body["port"] == 7800 and body["decomp_steps"] == 45
            and body["decomp_group_offload"] is True):
        fails.append(("config coercion", "MISMATCH",
                      f"port={body['port']} steps={body['decomp_steps']} "
                      f"offload={body['decomp_group_offload']}"))
    if body["api_key"] != "******":
        fails.append(("secret mask", "NOT MASKED", str(body["api_key"])))
    if "sk-test-secret" in r.text:
        fails.append(("secret leak", "RAW IN RESPONSE", ""))

secrets_on_disk = config_mod.SECRETS_FILE
if secrets_on_disk.exists() and "sk-test-secret" not in secrets_on_disk.read_text(encoding="utf-8"):
    fails.append(("secrets file", "KEY NOT SAVED", str(secrets_on_disk)))
cfg_on_disk = config_mod.CONFIG_FILE
if cfg_on_disk.exists() and "sk-test-secret" in cfg_on_disk.read_text(encoding="utf-8"):
    fails.append(("separation", "KEY IN config.json", str(cfg_on_disk)))
print(f"      密钥写入 secrets.json: {secrets_on_disk.exists()}")
print(f"      config.json 无密钥: {not (cfg_on_disk.exists() and 'sk-' in cfg_on_disk.read_text(encoding='utf-8'))}")

r = check("PUT /api/config (掩码回传不改密钥)", lambda: c.put(
    "/api/config", json={"patch": {"api_key": "******", "api_model": "m1"}}))
r = check("GET /api/config (验证掩码回传)", lambda: c.get("/api/config"))
if r and r.json().get("api_key") != "******":
    fails.append(("mask passthrough", "KEY LOST", r.text[:200]))

# ---------------------------------------------------------------- 任务
r = check("GET /api/tasks/stages", lambda: c.get("/api/tasks/stages"))
if r and len(r.json()) != 5:
    fails.append(("stages count", "MISMATCH", str(r.json())))

r = check("POST /api/tasks (create, no run)", lambda: c.post(
    "/api/tasks", json={"name": "冒烟任务", "prompt": "测试", "run": False}))
tid = r.json()["id"] if r else None
print(f"      task_id={tid}")

check("GET /api/tasks", lambda: c.get("/api/tasks"))
check("GET /api/tasks/{id}", lambda: c.get(f"/api/tasks/{tid}"))

# 上传一张测试图接管第 1 步
from PIL import Image  # noqa: E402

buf = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
Image.new("RGBA", (512, 512), (200, 120, 90, 255)).save(buf.name)

with open(buf.name, "rb") as f:
    check("POST input/generate (upload)", lambda: c.post(
        f"/api/tasks/{tid}/input/generate",
        files={"file": ("source.png", f, "image/png")}))

r = check("GET task after upload", lambda: c.get(f"/api/tasks/{tid}"))
if r:
    st = r.json()["stages"]["generate"]
    print(f"      generate.status={st['status']} artifacts={st['artifacts']}")
    if st["status"] != "done":
        fails.append(("upload takeover", "NOT DONE", str(st)[:200]))

# 文件服务 + 路径穿越防护
r = check("GET files/generate/source.png", lambda: c.get(
    f"/api/tasks/{tid}/files/generate/source.png"))
if r and "image" not in r.headers.get("content-type", ""):
    fails.append(("file serve", "WRONG CT", r.headers.get("content-type", "")))

for label, path in (("encoded ../", "..%2f..%2f..%2frequirements.txt"),
                    ("win ..\\", "%2e%2e%5c%2e%2e%5c%2e%2e%5crequirements.txt")):
    r = check(f"traversal guard ({label})", lambda p=path: c.get(
        f"/api/tasks/{tid}/files/{p}"), expect=(403, 404))
    if r:
        print(f"      blocked -> {r.status_code}")

check("GET unknown task", lambda: c.get("/api/tasks/nope-404"), expect=(404,))

# ---------------------------------------------------------------- 队列与错误流转
# 从 preview 重跑：rig 阶段没有 moc3，会快速失败——既验证队列又验证错误状态
check("POST run (from preview)", lambda: c.post(
    f"/api/tasks/{tid}/run", json={"from_stage": "preview"}))

status = None
for _ in range(40):
    time.sleep(0.25)
    status = c.get(f"/api/tasks/{tid}").json()["status"]
    if status in ("error", "done"):
        break
print(f"      队列执行后 status={status}")
if status != "error":
    fails.append(("queue execution", "NOT ERROR", str(status)))

check("POST reset/preview", lambda: c.post(f"/api/tasks/{tid}/reset/preview"))
check("DELETE /api/tasks/{id}", lambda: c.delete(f"/api/tasks/{tid}"))
r = check("GET deleted task", lambda: c.get(f"/api/tasks/{tid}"), expect=(404,))

# websocket：未知任务应立刻被服务端关闭
ws_ok = False
try:
    with c.websocket_connect(f"/api/tasks/{tid}/ws") as ws:
        data = ws.receive_json(timeout=3)
        print(f"[OK  ] ws 返回 {data.get('type')}")
        ws_ok = data.get("type") == "error"
        try:
            ws.receive(timeout=3)
            print("[FAIL] ws 未关闭")
            ws_ok = False
        except Exception:
            pass
except Exception:
    print("[OK  ] ws 连接被服务端关闭")
    ws_ok = True
if not ws_ok:
    fails.append(("ws deleted task", "STAYED OPEN", ""))

# ---------------------------------------------------------------- 结果
print("\n" + "=" * 50)
if fails:
    print(f"{len(fails)} 项失败：")
    for f_ in fails:
        print("  -", f_)
    sys.exit(1)
print("全部通过")
