import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, profile, resumes, tailor
from app.core.config import get_settings
from app.services.storage import ensure_bucket

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        ensure_bucket()
    except Exception as exc:  # noqa: BLE001 - storage may not be up yet in dev
        logger.warning("Could not verify object storage bucket: %s", exc)
    if not settings.llm_enabled:
        logger.warning(
            "ANTHROPIC_API_KEY is not set — resume parsing will use the heuristic "
            "fallback. Get a key at https://console.anthropic.com/settings/keys"
        )
    yield


app = FastAPI(
    title="Agent Applications API",
    description="Job application autopilot. The agent prepares; the user submits.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(profile.router, prefix="/api/v1")
app.include_router(resumes.router, prefix="/api/v1")
app.include_router(tailor.router, prefix="/api/v1")


@app.get("/health", tags=["meta"])
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "environment": settings.environment,
        "llm_enabled": settings.llm_enabled,
    }
