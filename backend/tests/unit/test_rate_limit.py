"""
#33 — Tests del rate limiting de la API (ventana deslizante por IP).
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.utils.rate_limit import SlidingWindowRateLimiter, _parse_rule

pytestmark = pytest.mark.asyncio


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SlidingWindowRateLimiter)

    @app.post("/auth/login")
    async def login():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"ok": True}

    return app


class TestParseRule:
    def test_valid(self):
        assert _parse_rule("5/60", (1, 1.0)) == (5, 60.0)

    def test_invalid_falls_back_to_default(self):
        assert _parse_rule("garbage", (7, 30.0)) == (7, 30.0)

    def test_none_falls_back(self):
        assert _parse_rule(None, (3, 10.0)) == (3, 10.0)


async def test_login_blocked_after_limit():
    """El 6º intento de login desde la misma IP retorna 429 con Retry-After."""
    with patch("app.utils.rate_limit.settings") as mock_settings:
        mock_settings.RATE_LIMIT_ENABLED = True
        mock_settings.RATE_LIMIT_LOGIN = "5/60"
        mock_settings.RATE_LIMIT_UPLOAD = "20/60"

        app = _make_app()
        transport = ASGITransport(app=app, client=("10.0.0.1", 12345))
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            for i in range(5):
                resp = await c.post("/auth/login")
                assert resp.status_code == 200, f"intento {i + 1}"

            resp = await c.post("/auth/login")
            assert resp.status_code == 429
            assert "Retry-After" in resp.headers
            assert "Demasiadas solicitudes" in resp.json()["detail"]


async def test_different_ips_have_independent_limits():
    """El límite es por IP: otra IP no queda bloqueada."""
    with patch("app.utils.rate_limit.settings") as mock_settings:
        mock_settings.RATE_LIMIT_ENABLED = True
        mock_settings.RATE_LIMIT_LOGIN = "2/60"
        mock_settings.RATE_LIMIT_UPLOAD = "20/60"

        app = _make_app()

        t1 = ASGITransport(app=app, client=("10.0.0.1", 1))
        async with AsyncClient(transport=t1, base_url="http://t") as c:
            await c.post("/auth/login")
            await c.post("/auth/login")
            assert (await c.post("/auth/login")).status_code == 429

        t2 = ASGITransport(app=app, client=("10.0.0.2", 2))
        async with AsyncClient(transport=t2, base_url="http://t") as c:
            assert (await c.post("/auth/login")).status_code == 200


async def test_unprotected_routes_not_limited():
    """Las rutas sin regla no se limitan."""
    with patch("app.utils.rate_limit.settings") as mock_settings:
        mock_settings.RATE_LIMIT_ENABLED = True
        mock_settings.RATE_LIMIT_LOGIN = "1/60"
        mock_settings.RATE_LIMIT_UPLOAD = "20/60"

        app = _make_app()
        transport = ASGITransport(app=app, client=("10.0.0.3", 3))
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            for _ in range(10):
                assert (await c.get("/health")).status_code == 200


async def test_disabled_via_setting():
    """Con RATE_LIMIT_ENABLED=false no se aplica ningún límite."""
    with patch("app.utils.rate_limit.settings") as mock_settings:
        mock_settings.RATE_LIMIT_ENABLED = False
        mock_settings.RATE_LIMIT_LOGIN = "1/60"
        mock_settings.RATE_LIMIT_UPLOAD = "20/60"

        app = _make_app()
        transport = ASGITransport(app=app, client=("10.0.0.4", 4))
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            for _ in range(5):
                assert (await c.post("/auth/login")).status_code == 200
