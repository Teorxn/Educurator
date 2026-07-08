"""
Shim de compatibilidad: langfuse SDK v2 + langchain-core 1.x.

La integración langchain de langfuse 2.x importa rutas legacy
(`langchain.callbacks.base`, `langchain.schema.agent`,
`langchain.schema.document`) que langchain 1.x eliminó — las clases
viven ahora en langchain_core. Este shim registra módulos alias en
sys.modules ANTES de importar langfuse.callback, para que esos imports
legacy resuelvan a las clases reales de langchain_core.

No requiere tener instalado el meta-paquete `langchain`: si no existe,
se crea un stub. Actualizar langfuse al SDK v3 eliminaría este shim,
pero exige migrar el servidor a Langfuse v3 (Clickhouse + Redis + S3),
demasiada infraestructura para este proyecto.
"""

import sys
import types


def install_legacy_langchain_shims() -> None:
    """Registra los módulos legacy de langchain que langfuse v2 espera."""
    if "langchain.schema.agent" in sys.modules:
        return  # ya instalado

    from langchain_core.agents import AgentAction, AgentFinish
    from langchain_core.callbacks.base import BaseCallbackHandler
    from langchain_core.documents import Document

    # Paquete raíz: usar el real si está instalado, stub si no
    try:
        import langchain  # type: ignore[import-untyped]
    except ImportError:
        langchain = types.ModuleType("langchain")
        sys.modules["langchain"] = langchain

    cb_pkg = types.ModuleType("langchain.callbacks")
    cb_base = types.ModuleType("langchain.callbacks.base")
    cb_base.BaseCallbackHandler = BaseCallbackHandler  # type: ignore[attr-defined]
    cb_pkg.base = cb_base  # type: ignore[attr-defined]

    schema_pkg = types.ModuleType("langchain.schema")
    schema_agent = types.ModuleType("langchain.schema.agent")
    schema_agent.AgentAction = AgentAction  # type: ignore[attr-defined]
    schema_agent.AgentFinish = AgentFinish  # type: ignore[attr-defined]
    schema_doc = types.ModuleType("langchain.schema.document")
    schema_doc.Document = Document  # type: ignore[attr-defined]
    schema_pkg.agent = schema_agent  # type: ignore[attr-defined]
    schema_pkg.document = schema_doc  # type: ignore[attr-defined]

    sys.modules.setdefault("langchain.callbacks", cb_pkg)
    sys.modules.setdefault("langchain.callbacks.base", cb_base)
    sys.modules.setdefault("langchain.schema", schema_pkg)
    sys.modules.setdefault("langchain.schema.agent", schema_agent)
    sys.modules.setdefault("langchain.schema.document", schema_doc)

    # Que los accesos por atributo también funcionen
    if not hasattr(langchain, "callbacks"):
        langchain.callbacks = cb_pkg  # type: ignore[attr-defined]
    if not hasattr(langchain, "schema"):
        langchain.schema = schema_pkg  # type: ignore[attr-defined]
