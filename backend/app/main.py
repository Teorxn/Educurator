import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# "Skipping data after last boundary": warning benigno de python-multipart
# al parsear uploads cuyo body trae bytes residuales tras el boundary final
# (lo hacen algunos clientes como axios). No indica ningún problema.
logging.getLogger("python_multipart").setLevel(logging.ERROR)
logging.getLogger("multipart").setLevel(logging.ERROR)

from app.api import analysis, analytics, auth, docs, reference_docs, suggestions
from app.config import settings
from app.utils.rate_limit import SlidingWindowRateLimiter


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

# ── Rate limiting (#33): login y upload, ventana deslizante por IP ──────────
app.add_middleware(SlidingWindowRateLimiter)

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
