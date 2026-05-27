from fastapi.staticfiles import StaticFiles
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.routes import router as router_agent
from app.api import telegram_routes
from app.agents.graph import setup_graph


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await setup_graph()
    yield


app = FastAPI(
    title="Lớn Rồi Đừng Lười AI Agents",
    description="Hệ thống tự động hóa nội dung Fanpage",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Routes ──
app.include_router(router_agent,      prefix="/api/v1")
app.include_router(telegram_routes.router,      prefix="/api/v1")

# Đảm bảo thư mục lưu media tồn tại và mount thành Static Files để xem qua web
os.makedirs("assets/images", exist_ok=True)
os.makedirs("assets/videos", exist_ok=True)
app.mount("/assets", StaticFiles(directory="assets"), name="assets")