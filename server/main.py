"""FastAPI 应用工厂与服务入口。python run.py 或 .venv\\Scripts\\python.exe -m server.main"""

from __future__ import annotations

import argparse
import logging
import webbrowser

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .api import system_router, tasks_router

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")


def create_app() -> FastAPI:
    app = FastAPI(title="Live2D AI 生成器", version="2.0.0",
                  description="AI 生图 → 一张图 → 可动 Live2D 模型，全流程本地运行")

    app.include_router(tasks_router)
    app.include_router(system_router)

    app.mount("/vendor", StaticFiles(directory=str(config.VENDOR_DIR)), name="vendor")
    app.mount("/static", StaticFiles(directory=str(config.WEB_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(config.WEB_DIR / "index.html")

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"ok": True}

    return app


app = create_app()


def main() -> None:
    cfg = config.load()
    parser = argparse.ArgumentParser(description="Live2D AI 生成器")
    parser.add_argument("--host", default=str(cfg.get("host") or "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(cfg.get("port") or 7800))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    import uvicorn

    from .envcheck import full_report

    url = f"http://{args.host}:{args.port}"
    rep = full_report()
    gpu = rep["gpu"]
    print("=" * 60)
    print("  Live2D AI 生成器 v2")
    print(f"  控制台地址：{url}")
    print(f"  工作目录：{config.WORKSPACE_DIR}")
    print(f"  Python {rep['python']['version']}")
    print("  GPU: " + (f"{gpu['name']} ({gpu['vram_gb']}GB)" if gpu["available"] else "未探测到 NVIDIA GPU"))
    print(f"  see-through: {'就绪' if rep['tools']['see_through']['ok'] else rep['tools']['see_through']['note']}")
    print(f"  image2live2d: {'就绪' if rep['tools']['image2live2d']['ok'] else rep['tools']['image2live2d']['note']}")
    print(f"  网页预览依赖: {'就绪' if rep['vendor']['ok'] else '缺失，请在设置页点「下载依赖」'}")
    print("=" * 60)

    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
