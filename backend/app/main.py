import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analysis, analytics, auth, docs, reference_docs, suggestions
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    except asyncio.CancelledError:
        # Shutdown normal del servidor — no propaga el error
        pass


app = FastAPI(
    title="EduCurator AI API",
    description="Sistema agéntico de curación de bases de conocimiento para cursos universitarios",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ─────────────────────────────────────────────────────────────────
app.include_router(analysis.router)
app.include_router(auth.router)
app.include_router(docs.router)
app.include_router(suggestions.router)
app.include_router(analytics.router)
app.include_router(reference_docs.router)


# ── Health check ────────────────────────────────────────────────────────────
@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "service": "educurator-api", "version": "1.0.0"}
