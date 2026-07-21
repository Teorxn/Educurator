"""Schemas de registro, perfil académico y administración de roles.

HU-29 — Registrarme como profesor (perfil académico)
HU-30 — Administrar roles del sistema
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.models import UserRole


# ── HU-29: registro y perfil académico ───────────────────────────────────────


class RegisterRequest(BaseModel):
    """Registro público de un docente con su perfil académico."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=3, max_length=255)
    profession: str | None = Field(default=None, max_length=255)
    # Obligatorio: al menos 1 materia (criterio de aceptación de HU-29)
    subjects: list[str] = Field(min_length=1)
    specialties: list[str] = Field(default_factory=list)
    courses_taught: list[str] = Field(default_factory=list)

    @field_validator("subjects", "specialties", "courses_taught")
    @classmethod
    def clean_list(cls, v: list[str]) -> list[str]:
        """Normaliza listas multi-valor: sin vacíos, sin duplicados, recortadas."""
        seen: list[str] = []
        for item in v or []:
            s = (item or "").strip()
            if s and s not in seen:
                seen.append(s[:120])
        return seen[:20]

    @field_validator("subjects")
    @classmethod
    def subjects_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Debes indicar al menos una materia que impartes")
        return v


class UpdateProfileRequest(BaseModel):
    """Edición del perfil académico desde la configuración de cuenta."""

    full_name: str | None = Field(default=None, min_length=3, max_length=255)
    profession: str | None = Field(default=None, max_length=255)
    subjects: list[str] | None = None
    specialties: list[str] | None = None
    courses_taught: list[str] | None = None

    @field_validator("subjects", "specialties", "courses_taught")
    @classmethod
    def clean_list(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        seen: list[str] = []
        for item in v:
            s = (item or "").strip()
            if s and s not in seen:
                seen.append(s[:120])
        return seen[:20]


class UserProfileResponse(BaseModel):
    """Perfil completo del usuario (GET /api/users/me)."""

    id: uuid.UUID
    email: str
    full_name: str | None = None
    profession: str | None = None
    subjects: list[str] | None = None
    specialties: list[str] | None = None
    courses_taught: list[str] | None = None
    role: UserRole
    is_active: bool
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── HU-30: administración de roles ───────────────────────────────────────────


class RoleCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = Field(default_factory=list)


class RoleUpdateRequest(BaseModel):
    name: str | None = Field(
        default=None, min_length=2, max_length=50, pattern=r"^[a-z][a-z0-9_]*$"
    )
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = None


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    permissions: list[str] | None = None
    is_system: bool
    users_count: int = 0

    model_config = {"from_attributes": True}


class AssignRoleRequest(BaseModel):
    role: UserRole


class RoleChangeAuditEntry(BaseModel):
    """Entrada de auditoría de cambios de rol."""

    id: uuid.UUID
    action: str
    performed_by: uuid.UUID | None = None
    reason: str | None = None
    before_content: dict | None = None
    after_content: dict | None = None
    timestamp: datetime

    model_config = {"from_attributes": True}
