"""
#12 — Estado del grafo LangGraph para el agente de curación.

Define el schema de estado que fluye a través de los nodos del grafo.
Cada clave es un canal que los nodos pueden leer y escribir.
"""

from typing import Annotated, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


class AgentState(TypedDict):
    """Estado del flujo de curación de documentos.

    document_ids
        IDs UUID (en str) de los documentos a procesar.
        Los carga load_documents_node desde Postgres (status=needs_review).

    documents_text
        Mapa doc_id → texto plano extraído por el parser.
        Lo genera chunk_and_embed_node antes de chunkear.

    chunks
        Lista de resultados de chunk_and_embed.
        Cada entrada contiene chroma_id, chunk_index, text, token_count, hash, page_number.

    messages
        Mensajes del agente en formato LangChain BaseMessage.
        Usa el reducer add_messages para concatenar en lugar de sobrescribir.
        El ReAct agent lee de aquí y escribe sus respuestas.

    suggestions
        Lista de sugerencias estructuradas que generate_suggestions_node
        convertirá en registros Suggestion en Postgres.

    redundancy_findings
        Lista de pares redundantes detectados automáticamente por
        redundancy_detection_node. generate_suggestions_node los procesa
        y crea sugerencias de tipo 'redundancy'.

    error
        Mensaje de error si algún nodo falla. El grafo intenta continuar
        con los documentos restantes si es posible.
    """

    document_ids: List[str]
    documents_text: dict
    chunks: List[dict]
    messages: Annotated[List[BaseMessage], add_messages]
    suggestions: List[dict]
    redundancy_findings: List[dict]
    error: Optional[str]
