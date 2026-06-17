"""
Tests para HU-06: Analizar documentos automáticamente (API de análisis).

Verifica que:
  - El endpoint POST /api/analysis/curate dispara el análisis
  - El endpoint GET /api/analysis/status/{thread_id} consulta estado
  - El endpoint GET /api/analysis/runs lista corridas
  - Langfuse handler se crea correctamente (o se omite si no configurado)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.api.analysis import _runs
from app.api.dependencies import get_current_user
from app.main import app
from httpx import ASGITransport, AsyncClient

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_runs():
    """Limpia el registro de corridas entre tests."""
    _runs.clear()
    yield


@pytest.fixture
def mock_user():
    """Crea un usuario simulado para inyectar como dependencia."""
    return MagicMock(id="test-user-id", role="instructor")


@pytest.fixture(autouse=True)
def override_auth(mock_user):
    """Sobrescribe la dependencia get_current_user para todos los tests.

    Usamos app.dependency_overrides que es la forma oficial de FastAPI
    para reemplazar dependencias en tests.
    """
    app.dependency_overrides[get_current_user] = lambda: mock_user
    yield
    app.dependency_overrides.clear()


# ── Tests del endpoint POST /api/analysis/curate ─────────────────────────────


@pytest.mark.asyncio
async def test_trigger_curation_returns_accepted():
    """Verifica que POST /api/analysis/curate retorna 202 Accepted."""
    with patch("app.agents.graph.run_curation", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {
            "document_ids": [],
            "suggestions": [],
            "redundancy_findings": [],
        }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/analysis/curate")

        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert "thread_id" in data
        assert data["thread_id"].startswith("curation-")
        # Verificar que el análisis se ejecutó
        mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_curation_custom_thread_id():
    """Verifica que se puede pasar un thread_id personalizado."""
    with patch("app.agents.graph.run_curation", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {
            "document_ids": [],
            "suggestions": [],
            "redundancy_findings": [],
        }

        custom_tid = "mi-corrida-001"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/analysis/curate?thread_id={custom_tid}",
            )

        assert resp.status_code == 202
        data = resp.json()
        assert data["thread_id"] == custom_tid


@pytest.mark.asyncio
async def test_trigger_curation_stores_run_in_memory():
    """Verifica que la corrida se registra en _runs."""
    # No parcheamos run_curation para que la tarea en background no se ejecute.
    # En su lugar, parcheamos _execute_curation para que sea un no-op.
    with patch(
        "app.api.analysis._execute_curation", new_callable=AsyncMock
    ) as mock_execute:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/analysis/curate?thread_id=store-test")

        assert resp.status_code == 202
        tid = resp.json()["thread_id"]
        # La corrida debe estar registrada inmediatamente con status running
        assert tid in _runs
        assert _runs[tid]["status"] == "running"
        assert _runs[tid]["triggered_by"] == "test-user-id"
        # Verificar que NO se ejecutó realmente
        mock_execute.assert_awaited_once()


# ── Tests del endpoint GET /api/analysis/status ──────────────────────────────


@pytest.mark.asyncio
async def test_get_curation_status_running():
    """Verifica que GET /status retorna el estado 'running'."""
    tid = "test-run-001"
    _runs[tid] = {
        "thread_id": tid,
        "status": "running",
        "triggered_by": "user-1",
        "error": None,
        "result": None,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/analysis/status/{tid}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["thread_id"] == tid
    assert data["status"] == "running"


@pytest.mark.asyncio
async def test_get_curation_status_not_found():
    """Verifica que GET /status con thread_id inexistente retorna 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/analysis/status/nonexistent-run")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_curation_status_completed():
    """Verifica que GET /status retorna el resultado cuando está completado."""
    tid = "test-run-002"
    _runs[tid] = {
        "thread_id": tid,
        "status": "completed",
        "triggered_by": "user-1",
        "error": None,
        "result": {
            "documents_processed": 2,
            "document_ids": ["doc-1", "doc-2"],
            "suggestions_generated": 3,
            "redundancy_pairs_found": 1,
            "suggestions": [
                {
                    "id": "sug-1",
                    "document_id": "doc-1",
                    "type": "redundancy",
                    "confidence_score": 0.95,
                },
            ],
        },
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/analysis/status/{tid}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["result"]["documents_processed"] == 2
    assert data["result"]["suggestions_generated"] == 3
    assert data["result"]["redundancy_pairs_found"] == 1


# ── Tests del endpoint GET /api/analysis/runs ────────────────────────────────


@pytest.mark.asyncio
async def test_list_curation_runs_empty():
    """Verifica que GET /runs retorna lista vacía cuando no hay corridas."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/analysis/runs")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["runs"] == []


@pytest.mark.asyncio
async def test_list_curation_runs_with_data():
    """Verifica que GET /runs retorna las corridas registradas."""
    _runs["run-1"] = {
        "thread_id": "run-1",
        "status": "running",
        "triggered_by": "user-1",
        "error": None,
    }
    _runs["run-2"] = {
        "thread_id": "run-2",
        "status": "completed",
        "triggered_by": "user-2",
        "error": None,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/analysis/runs")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["runs"]) == 2


# ── Tests de Langfuse integration ────────────────────────────────────────────


def test_langfuse_handler_returns_none_when_not_configured():
    """Verifica que sin credenciales Langfuse, el handler es None."""
    from app.agents.graph import _create_langfuse_handler

    with patch("app.agents.graph.settings") as mock_settings:
        mock_settings.LANGFUSE_PUBLIC_KEY = ""
        mock_settings.LANGFUSE_SECRET_KEY = ""
        mock_settings.LANGFUSE_HOST = "https://cloud.langfuse.com"

        handler = _create_langfuse_handler()
        assert handler is None


def test_langfuse_handler_created_when_configured():
    """Verifica que con credenciales Langfuse, se crea el handler."""
    import sys

    from app.agents.graph import _create_langfuse_handler

    # Mock de los módulos langfuse para simular su presencia
    fake_callback_handler = MagicMock()
    fake_instance = MagicMock()
    fake_callback_handler.return_value = fake_instance

    fake_langfuse_callback = MagicMock(spec=object())
    fake_langfuse_callback.CallbackHandler = fake_callback_handler

    fake_langfuse = MagicMock(spec=object())
    fake_langfuse.callback = fake_langfuse_callback

    with patch.dict(
        sys.modules,
        {
            "langfuse": fake_langfuse,
            "langfuse.callback": fake_langfuse_callback,
        },
        clear=False,
    ):
        with patch("app.agents.graph.settings") as mock_settings:
            mock_settings.LANGFUSE_PUBLIC_KEY = "pk-test-123"
            mock_settings.LANGFUSE_SECRET_KEY = "sk-test-456"
            mock_settings.LANGFUSE_HOST = "https://cloud.langfuse.com"

            handler = _create_langfuse_handler()

    assert handler is fake_instance
    fake_callback_handler.assert_called_once_with(
        secret_key="sk-test-456",
        public_key="pk-test-123",
        host="https://cloud.langfuse.com",
    )


# ── Tests del helper _summarize_result ───────────────────────────────────────


def test_summarize_result_empty():
    """Verifica que _summarize_result maneja resultados vacíos."""
    from app.api.analysis import _summarize_result

    result = _summarize_result({})
    assert result["documents_processed"] == 0
    assert result["suggestions_generated"] == 0
    assert result["redundancy_pairs_found"] == 0
    assert result["suggestions_by_type"] == {}
    assert result["error"] is None


def test_summarize_result_with_data():
    """Verifica que _summarize_result estructura correctamente los datos."""
    from app.api.analysis import _summarize_result

    result = _summarize_result(
        {
            "document_ids": ["doc-1", "doc-2"],
            "suggestions": [
                {
                    "id": "s-1",
                    "document_id": "doc-1",
                    "type": "redundancy",
                    "confidence_score": 0.9,
                },
            ],
            "redundancy_findings": [{"chunk_id_a": "a", "chunk_id_b": "b"}],
            "error": None,
        }
    )
    assert result["documents_processed"] == 2
    assert result["suggestions_generated"] == 1
    assert result["suggestions_by_type"] == {"redundancy": 1}
    assert result["redundancy_pairs_found"] == 1
    assert result["suggestions"][0]["id"] == "s-1"
    assert result["error"] is None


def test_summarize_result_with_error():
    """Verifica que _summarize_result incluye errores del grafo."""
    from app.api.analysis import _summarize_result

    result = _summarize_result(
        {
            "document_ids": [],
            "suggestions": [],
            "redundancy_findings": [],
            "error": "Error procesando documento X",
        }
    )
    assert result["error"] == "Error procesando documento X"


def test_summarize_result_multiple_types():
    """Verifica el conteo de sugerencias por tipo."""
    from app.api.analysis import _summarize_result

    result = _summarize_result(
        {
            "document_ids": ["doc-1"],
            "suggestions": [
                {"id": "s-1", "type": "redundancy", "confidence_score": 0.9},
                {"id": "s-2", "type": "conflict", "confidence_score": 0.8},
                {"id": "s-3", "type": "redundancy", "confidence_score": 0.95},
            ],
        }
    )
    assert result["suggestions_by_type"] == {"redundancy": 2, "conflict": 1}


# ── Tests del endpoint GET /api/analysis/info ─────────────────────────────────


@pytest.mark.asyncio
async def test_get_analysis_info():
    """Verifica que GET /api/analysis/info retorna info del grafo."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/analysis/info")

    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "tools" in data
    assert "llm" in data
    assert "tracing" in data
    assert "checkpointer" in data


# ── Test de get_graph_info con tracing ───────────────────────────────────────


def test_graph_info_includes_tracing():
    """get_graph_info debe reportar el estado de Langfuse."""
    from app.agents.graph import get_graph_info

    info = get_graph_info()
    assert "tracing" in info
    assert "langfuse" in info["tracing"]
    assert "langfuse_configured" in info["tracing"]
    # Sin credenciales, debe ser False
    assert info["tracing"]["langfuse"] is False
    assert info["tracing"]["langfuse_configured"] is False
