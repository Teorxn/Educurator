"""Control de acceso a documentos.

Modelo de visibilidad:
  - Documentos 'reference' (corpus de referencia institucional: reglamentos,
    normativas, FAQs, libros de texto) son visibles para cualquier docente.
  - Documentos 'curated' (material propio de cada docente) son privados:
    solo su autor puede verlos/gestionarlos.
  - Los administradores ven y gestionan TODO, sin excepción.
"""

from sqlalchemy import ColumnElement, or_

from app.models.models import Document, DocumentCategory, User, UserRole


def visible_docs_filter(user: User) -> ColumnElement | None:
    """Condición SQL de visibilidad de documentos para `user`.

    Devuelve None cuando no hace falta filtrar (admin: ve todo).
    """
    if user.role == UserRole.admin:
        return None
    return or_(
        Document.category == DocumentCategory.reference,
        Document.uploaded_by == user.id,
    )


def can_access_doc(doc: Document, user: User) -> bool:
    """Si `user` puede ver/gestionar `doc` según el modelo de visibilidad."""
    if user.role == UserRole.admin:
        return True
    if doc.category == DocumentCategory.reference:
        return True
    return doc.uploaded_by == user.id
