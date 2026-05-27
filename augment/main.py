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
from augment.service import AugmentApp

UI_DIR = ROOT / "ui"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    app.state.augment = AugmentApp(load_config())
    yield
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


if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(UI_DIR)), name="ui")
