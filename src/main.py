import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.api.routes import router as api_router
from src.config import get_settings
from src.database import init_db
from src.agents.graph import THREAD_STORE

settings = get_settings()


async def periodic_thread_cleanup():
    """Background task định kỳ xóa HITL threads đã quá hạn 30 phút."""
    while True:
        try:
            await asyncio.sleep(300)  # Mỗi 5 phút
            THREAD_STORE.cleanup_expired()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Lifespan Cleanup Error]: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print(f"[App] Starting {settings.app_name} ({settings.app_env})...")
    init_db()
    cleanup_task = asyncio.create_task(periodic_thread_cleanup())
    
    yield
    
    # Shutdown
    print(f"[App] Shutting down {settings.app_name}...")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title=settings.app_name,
    version="2.0.0",
    description="High-Quality Enterprise Text-to-SQL Analytics Agent with Multi-Agent Tracing & Observability",
    lifespan=lifespan
)

# CORS Middleware
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routes
app.include_router(api_router, prefix="/api/v1")

# Static frontend serving
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend"))
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        index_path = os.path.join(frontend_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "Frontend index.html not found"}


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "env": settings.app_env, "version": "2.0.0"}
