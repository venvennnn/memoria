from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from apps.api.deps import get_pipeline, get_qdrant_store, get_settings
from apps.api.routers import commitments, demo, eval, health, memory, omi, receipts

load_dotenv()

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


async def _sweeper_loop() -> None:
    while True:
        await asyncio.sleep(15 * 60)
        try:
            pipeline = get_pipeline()
            pipeline.sweep_ttl()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    store = get_qdrant_store()
    try:
        store.ensure_collections()
    except Exception as exc:
        print(f"Qdrant bootstrap warning: {exc}")
    task = asyncio.create_task(_sweeper_loop())
    yield
    task.cancel()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Memoria", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(omi.router)
    app.include_router(demo.router)
    app.include_router(memory.router)
    app.include_router(commitments.router)
    app.include_router(receipts.router)
    app.include_router(eval.router)

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/")
        def index():
            return FileResponse(WEB_DIR / "index.html")

    return app


app = create_app()


def run():
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "apps.api.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "dev",
    )


if __name__ == "__main__":
    run()
