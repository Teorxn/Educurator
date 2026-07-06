"""
#33 — Rate limiting de la API (sin dependencias externas).

Middleware ASGI con ventana deslizante por IP para proteger endpoints
sensibles: login (fuerza bruta) y upload (abuso de almacenamiento).

Complementa el rate limiting del LLM (InMemoryRateLimiter en graph.py)
y de la búsqueda web (reintentos + cadena de fallback en registry.py).

Configuración (env):
    RATE_LIMIT_ENABLED=true
    RATE_LIMIT_LOGIN=5/60       # 5 intentos por 60s por IP
    RATE_LIMIT_UPLOAD=20/60     # 20 subidas por 60s por IP

Nota: el estado vive en memoria del proceso — suficiente para un solo
worker (MVP). Con múltiples réplicas se necesitaría Redis o el rate
limiting del reverse proxy (ver README, sección de producción).
"""

import logging
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

logger = logging.getLogger(__name__)


def _parse_rule(rule: str, default: tuple[int, float]) -> tuple[int, float]:
    """Parsea 'N/segundos' → (max_llamadas, ventana_segundos)."""
    try:
        n, window = rule.strip().split("/")
        return max(1, int(n)), max(1.0, float(window))
    except (ValueError, AttributeError):
        return default


class SlidingWindowRateLimiter(BaseHTTPMiddleware):
    """Rate limit por IP con ventana deslizante para rutas configuradas."""

    def __init__(self, app):
        super().__init__(app)
        self._enabled = getattr(settings, "RATE_LIMIT_ENABLED", True)
        # ruta (método, prefijo) → (max_llamadas, ventana_s)
        self._rules: dict[tuple[str, str], tuple[int, float]] = {
            ("POST", "/auth/login"): _parse_rule(
                getattr(settings, "RATE_LIMIT_LOGIN", "5/60"), (5, 60.0)
            ),
            ("POST", "/api/docs/upload"): _parse_rule(
                getattr(settings, "RATE_LIMIT_UPLOAD", "20/60"), (20, 60.0)
            ),
        }
        # (ruta, ip) → lista de timestamps recientes
        self._hits: dict[tuple[str, str], list[float]] = {}

    def _match_rule(self, method: str, path: str):
        for (m, prefix), rule in self._rules.items():
            if method == m and path.startswith(prefix):
                return prefix, rule
        return None, None

    async def dispatch(self, request: Request, call_next):
        if not self._enabled:
            return await call_next(request)

        prefix, rule = self._match_rule(request.method, request.url.path)
        if rule is None:
            return await call_next(request)

        max_calls, window = rule
        client_ip = request.client.host if request.client else "unknown"
        key = (prefix, client_ip)
        now = time.monotonic()

        timestamps = [t for t in self._hits.get(key, []) if t > now - window]
        if len(timestamps) >= max_calls:
            retry_after = int(timestamps[0] + window - now) + 1
            logger.warning(
                "⛔ Rate limit: %s %s desde %s (%d/%ds)",
                request.method,
                prefix,
                client_ip,
                max_calls,
                int(window),
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"Demasiadas solicitudes. Intenta de nuevo en "
                        f"{retry_after}s."
                    )
                },
                headers={"Retry-After": str(retry_after)},
            )

        timestamps.append(now)
        self._hits[key] = timestamps

        # Poda periódica para que el dict no crezca sin límite
        if len(self._hits) > 10_000:
            cutoff = now - max(w for _, w in self._rules.values())
            self._hits = {
                k: [t for t in v if t > cutoff]
                for k, v in self._hits.items()
                if any(t > cutoff for t in v)
            }

        return await call_next(request)
