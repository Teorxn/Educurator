"""
Reconstruye el índice vectorial de ChromaDB a partir de Postgres.

Los chunks se escriben a Chroma únicamente dentro del pipeline
(chunk_and_embed_node), así que si el índice se pierde o se desincroniza los
documentos ya procesados NO vuelven solos: el chat deja de encontrar
contexto aunque `document_chunks` siga intacto en Postgres.

Este script rehace el índice desde esa tabla, que guarda el texto de cada
chunk junto a su chroma_id. Es idempotente: por defecto sólo sube los chunks
que faltan en la colección.

Uso:
    python reindex_chroma.py                 # sólo lo que falta
    python reindex_chroma.py --force         # re-embebe todo
    python reindex_chroma.py --doc <uuid>    # acota a un documento
    python reindex_chroma.py --dry-run       # sólo reporta, no escribe
"""
import argparse
import hashlib
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import Document, DocumentChunk
from app.rag.embeddings import (
    _get_collection,
    _get_embedding_model,
)

# psycopg2 en vez de asyncpg, igual que seed.py (evita problemas en Windows)
db_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
engine = create_engine(db_url)

# Lote de subida a Chroma. Los embeddings se calculan en el mismo tamaño para
# no cargar en memoria documentos grandes de una sola vez.
BATCH_SIZE = 64


def _load_rows(doc_id: str | None) -> list[tuple[DocumentChunk, Document]]:
    """Trae los chunks con su documento (se necesita la categoría)."""
    with Session(engine) as db:
        query = (
            select(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
        )
        if doc_id:
            query = query.where(Document.id == doc_id)
        return list(db.execute(query).all())


def _existing_ids(collection, ids: list[str]) -> set[str]:
    """IDs ya presentes en la colección (consulta por lotes)."""
    found: set[str] = set()
    for i in range(0, len(ids), 500):
        batch = ids[i : i + 500]
        try:
            res = collection.get(ids=batch, include=[])
            found.update(res.get("ids") or [])
        except Exception as e:
            # Sin este dato el script sigue siendo correcto: sólo pierde la
            # optimización de saltar lo ya indexado.
            print(f"  ! No se pudo consultar el índice existente: {e}")
            return set()
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doc", help="UUID de un documento concreto")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embebe también los chunks ya presentes en el índice",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Reporta qué haría, sin escribir en ChromaDB",
    )
    args = parser.parse_args()

    rows = _load_rows(args.doc)
    if not rows:
        print("No hay chunks en Postgres para reindexar.")
        return 0

    print(f"Chunks en Postgres: {len(rows)}")

    collection = _get_collection()
    print(f"Colección '{collection.name}': {collection.count()} elementos")

    # El chroma_id es el vínculo entre ambas bases; si falta se reconstruye
    # con la misma convención que chunk_and_embed.
    pending: list[tuple[str, DocumentChunk, Document]] = []
    for chunk, doc in rows:
        chroma_id = chunk.chroma_id or f"{doc.id}_chunk_{chunk.chunk_index}"
        pending.append((chroma_id, chunk, doc))

    if not args.force:
        already = _existing_ids(collection, [cid for cid, _, _ in pending])
        skipped = len(already)
        pending = [item for item in pending if item[0] not in already]
        print(f"Ya indexados: {skipped} — pendientes: {len(pending)}")

    if not pending:
        print("El índice ya está al día.")
        return 0

    if args.dry_run:
        docs_afectados = {str(doc.id) for _, _, doc in pending}
        print(
            f"[dry-run] Se subirían {len(pending)} chunks "
            f"de {len(docs_afectados)} documento(s). Nada fue escrito."
        )
        return 0

    model = _get_embedding_model()
    subidos = 0

    for i in range(0, len(pending), BATCH_SIZE):
        batch = pending[i : i + BATCH_SIZE]
        texts = [chunk.content for _, chunk, _ in batch]
        embeddings = model.encode(
            texts, batch_size=32, show_progress_bar=False
        ).tolist()

        # upsert (no add): reindexar dos veces no debe duplicar ni fallar.
        collection.upsert(
            ids=[cid for cid, _, _ in batch],
            embeddings=embeddings,
            documents=texts,
            metadatas=[
                {
                    "doc_id": str(doc.id),
                    "chunk_index": chunk.chunk_index,
                    "page_number": chunk.page_number or 0,
                    "hash": chunk.hash
                    or hashlib.sha256(chunk.content.encode()).hexdigest(),
                    "token_count": chunk.token_count,
                    "category": doc.category.value,
                }
                for _, chunk, doc in batch
            ],
        )
        subidos += len(batch)
        print(f"  {subidos}/{len(pending)} chunks indexados")

    print(f"Listo. Colección '{collection.name}': {collection.count()} elementos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
