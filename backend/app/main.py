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

from app.api import (
    analysis,
    analytics,
    auth,
    chat,
    dashboard,
    docs,
    reference_docs,
    suggestions,
    users,
)
from app.config import settings
from app.utils.rate_limit import SlidingWindowRateLimiter


async def _preload_embedding_model() -> None:
    """Precarga el modelo de embeddings en segundo plano al arrancar.

    Sin esto, el PRIMER upload paga los ~10-20s de carga de
    sentence-transformers dentro de su propia corrida. La precarga corre
    en un thread y no bloquea el arranque del servidor.
    """
    import logging as _logging

    log = _logging.getLogger("app.startup")
    try:
        from app.rag.embeddings import get_embedding_model

        await asyncio.to_thread(get_embedding_model)
        log.info("✅ Modelo de embeddings precargado — el primer upload no espera")
    except Exception as e:
        # No es fatal: se cargará perezosamente en el primer uso
        log.warning("⚠️  No se pudo precargar el modelo de embeddings: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    preload_task = asyncio.create_task(_preload_embedding_model())

    # HU-22/23 — worker que procesa la cola de curación secuencialmente
    from app.services.curation_queue import start_worker, stop_worker

    start_worker()
    try:
        yield
    except asyncio.CancelledError:
        # Shutdown normal del servidor — no propaga el error
        pass
    finally:
        stop_worker()
        if not preload_task.done():
            preload_task.cancel()


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
app.include_router(users.router)
app.include_router(chat.router)
app.include_router(dashboard.router)


# ── Health check ────────────────────────────────────────────────────────────
@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "service": "educurator-api", "version": "1.0.0"}
