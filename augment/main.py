from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from augment.api.chat import router as chat_router
from augment.api.meta import router as meta_router
from augment.config import ROOT, load_config
from augment.logging import configure_logging, get_logger
from augment.service import AugmentApp

UI_DIR = ROOT / "ui"
ASSETS_DIR = ROOT / "assets"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    config = load_config()
    configure_logging(config.data_dir)
    get_logger("main").info("starting Augment")
    app.state.augment = AugmentApp(config)
    yield
    get_logger("main").info("stopping Augment")
    await app.state.augment.close()


app = FastAPI(title="Augment", lifespan=lifespan)
app.include_router(chat_router)
app.include_router(meta_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(UI_DIR / "index.html"))


@app.get("/favicon.ico")
async def favicon() -> FileResponse:
    return FileResponse(str(ASSETS_DIR / "augment-logo.svg"), media_type="image/svg+xml")


if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(UI_DIR)), name="ui")
