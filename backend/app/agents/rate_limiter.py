"""
Rate limiter para APIs externas (LLM, web search, etc.).

Usa una ventana deslizante para limitar el número de llamadas
en un período de tiempo. Útil para cuotas gratuitas como Gemini
(5 requests/minuto) o APIs con límites estrictos.
"""

import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class AsyncRateLimiter:
    """Rate limiter asíncrono con ventana deslizante.

    Uso:
        limiter = AsyncRateLimiter(max_calls=4, window_seconds=60.0)
        await limiter.acquire()  # Espera hasta tener un slot disponible
        # ... hacer llamada API ...
    """

    def __init__(self, max_calls: int, window_seconds: float = 60.0):
        if max_calls < 1:
            raise ValueError("max_calls debe ser >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds debe ser > 0")

        self._max_calls = max_calls
        self._window = window_seconds
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """Espera hasta que haya un slot disponible.

        Returns:
            Tiempo de espera real (0.0 si no hubo espera).
        """
        while True:
            async with self._lock:
                now = time.monotonic()
                cutoff = now - self._window
                # Podar timestamps expirados
                self._timestamps = [t for t in self._timestamps if t > cutoff]
                if len(self._timestamps) < self._max_calls:
                    self._timestamps.append(now)
                    return 0.0
                # Calcular cuánto esperar hasta el próximo slot
                wait = self._timestamps[0] + self._window - now

            if wait > 0:
                logger.info(
                    "⏱  Rate limiter: esperando %.1fs (límite: %d llamadas/%ds)",
                    wait,
                    self._max_calls,
                    self._window,
                )
                await asyncio.sleep(wait)

    @property
    def remaining(self) -> int:
        """Retorna cuántas llamadas quedan en la ventana actual (aproximado)."""
        now = time.monotonic()
        cutoff = now - self._window
        active = sum(1 for t in self._timestamps if t > cutoff)
        return max(0, self._max_calls - active)

    def reset(self):
        """Reinicia el contador (útil para tests)."""
        self._timestamps.clear()


# ── Singleton global para Gemini ──────────────────────────────────────────────
# Free tier: 5 requests/minute → usamos 4 para dejar margen de seguridad
gemini_rate_limiter = AsyncRateLimiter(max_calls=4, window_seconds=60.0)
