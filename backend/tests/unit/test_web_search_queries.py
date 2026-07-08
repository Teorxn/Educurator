"""
Tests de la generación de consultas web de calidad y de la inyección
de evidencia web al contexto del agente ReAct.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.nodes import (
    _build_web_queries,
    _clean_filename_query,
    _pick_content_sentence,
)

pytestmark = pytest.mark.asyncio


class TestCleanFilenameQuery:
    def test_removes_extension_and_separators(self):
        assert (
            _clean_filename_query("Curso_Induccion-seguridad.pdf")
            == "Curso Induccion seguridad"
        )

    def test_removes_version_noise(self):
        q = _clean_filename_query("Lineamientos_Producto_Original v2.pdf")
        assert "Original" not in q and "v2" not in q
        assert "Lineamientos" in q and "Producto" in q


class TestPickContentSentence:
    def test_skips_form_headers(self):
        """El bug clásico: 'Código: GDC-FR-15 Versión 004' no es una consulta."""
        chunks = [
            {
                "text": (
                    "Código: GDC-FR-15 Versión 004 FINAL PROJECT / SCRIPT. "
                    "La fotosíntesis es el proceso por el cual las plantas "
                    "convierten la luz solar en energía química aprovechable."
                )
            }
        ]
        sentence = _pick_content_sentence(chunks)
        assert "GDC-FR-15" not in sentence
        assert "fotosíntesis" in sentence

    def test_empty_when_only_noise(self):
        chunks = [{"text": "Código: ABC-XY-01 Versión 002. Página 3. 12/05/2026."}]
        assert _pick_content_sentence(chunks) == ""


async def test_build_web_queries_uses_filename_and_sentence():
    doc_id = str(uuid.uuid4())
    state = {
        "document_ids": [doc_id],
        "chunks": [
            {
                "text": (
                    "El teorema de Pitágoras relaciona los catetos con la "
                    "hipotenusa en todo triángulo rectángulo del plano."
                )
            }
        ],
    }

    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = [("Geometria_Basica_Curso.pdf",)]
    session.execute = AsyncMock(return_value=result)
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("app.agents.nodes.AsyncSessionLocal", new=factory):
        queries = await _build_web_queries(state)

    assert len(queries) == 2
    assert queries[0] == "Geometria Basica Curso"
    assert "Pitágoras" in queries[1]


async def test_react_agent_receives_web_evidence():
    """_safe_react_agent_node inyecta los resultados web como mensaje."""
    import app.agents.graph as g

    captured = {}

    async def fake_ainvoke(state):
        captured["state"] = state
        return {}

    fake_agent = MagicMock()
    fake_agent.ainvoke = fake_ainvoke

    state = {
        "messages": [],
        "web_search_results": [
            {
                "title": "Normativa oficial",
                "url": "https://ejemplo.edu/norma",
                "snippet": "La duración mínima del curso es de 40 horas.",
            }
        ],
    }

    with patch.object(g, "_react_agent", fake_agent):
        await g._safe_react_agent_node(state)

    msgs = captured["state"]["messages"]
    assert len(msgs) == 1
    content = msgs[0].content
    assert "EVIDENCIA WEB" in content
    assert "https://ejemplo.edu/norma" in content
    assert "source_web_url" in content


async def test_react_agent_without_web_results_no_injection():
    """Sin resultados web no se inyecta ningún mensaje extra."""
    import app.agents.graph as g

    captured = {}

    async def fake_ainvoke(state):
        captured["state"] = state
        return {}

    fake_agent = MagicMock()
    fake_agent.ainvoke = fake_ainvoke

    with patch.object(g, "_react_agent", fake_agent):
        await g._safe_react_agent_node({"messages": [], "web_search_results": []})

    assert captured["state"]["messages"] == []
