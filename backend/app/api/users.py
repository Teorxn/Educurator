"""
HU-29 — Registrarme como profesor (registro + perfil académico)
HU-30 — Administrar roles del sistema (RBAC + auditoría)

Endpoints:
  POST   /auth/register           → registro público de docente
  GET    /api/users/me            → perfil propio
  PATCH  /api/users/me            → editar perfil académico
  GET    /api/roles               → listar roles + usuarios asignados (admin)
  POST   /api/roles               → crear rol (admin)
  PATCH  /api/roles/{id}          → editar rol no-system (admin)
  DELETE /api/roles/{id}          → eliminar rol no-system (admin)
  PATCH  /api/users/{id}/role     → asignar rol con auditoría (admin)
  GET    /api/users/role-audit    → historial de cambios de rol (admin)
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.models import DocumentHistory, Role, User, UserRole
from app.schemas.auth import TokenResponse
from app.schemas.users import (
    AssignRoleRequest,
    RegisterRequest,
    RoleChangeAuditEntry,
    RoleCreateRequest,
    RoleResponse,
    RoleUpdateRequest,
    UpdateProfileRequest,
    UserProfileResponse,
)
from app.utils.security import create_access_token, hash_password

logger = logging.getLogger(__name__)

router = APIRouter(tags=["users & roles"])

# Acción con la que se registran los cambios de rol en la auditoría
ROLE_CHANGE_ACTION = "role_changed"


# ── HU-29: Registro público de docente ───────────────────────────────────────


@router.post(
    "/auth/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Registra un docente con su perfil académico y devuelve su token.

    El perfil (materias, especialidades, cursos) permite al agente
    personalizar sus recomendaciones. La contraseña se almacena hasheada
    con bcrypt; nunca en texto plano.
    """
    existing = (
        await db.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una cuenta registrada con ese correo electrónico",
        )

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        profession=body.profession,
        subjects=body.subjects,
        specialties=body.specialties,
        courses_taught=body.courses_taught,
        role=UserRole.instructor,  # el registro público nunca crea admins
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info("👤 Nuevo docente registrado: %s", user.email)
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return TokenResponse(access_token=token)


# ── HU-29: Perfil propio ─────────────────────────────────────────────────────


@router.get("/api/users/me", response_model=UserProfileResponse)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """Perfil académico del usuario autenticado."""
    return current_user


@router.patch("/api/users/me", response_model=UserProfileResponse)
async def update_my_profile(
    body: UpdateProfileRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edita el perfil académico propio (no permite cambiar rol ni email)."""
    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    if not updates:
        return current_user

    user = (
        await db.execute(select(User).where(User.id == current_user.id))
    ).scalar_one()
    for field, value in updates.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user


# ── HU-30: CRUD de roles ─────────────────────────────────────────────────────


async def _role_with_counts(db: AsyncSession, role: Role) -> RoleResponse:
    """Adjunta el número de usuarios asignados al rol."""
    count = 0
    try:
        enum_role = UserRole(role.name)
        count = (
            await db.execute(
                select(func.count()).select_from(User).where(User.role == enum_role)
            )
        ).scalar_one()
    except ValueError:
        # Rol personalizado: aún no hay usuarios con ese valor en el enum
        count = 0
    return RoleResponse(
        id=role.id,
        name=role.name,
        description=role.description,
        permissions=role.permissions or [],
        is_system=role.is_system,
        users_count=count,
    )


@router.get("/api/roles", response_model=list[RoleResponse])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin)),
):
    """Lista los roles del sistema con el conteo de usuarios asignados."""
    roles = list(
        (await db.execute(select(Role).order_by(Role.created_at))).scalars().all()
    )
    return [await _role_with_counts(db, r) for r in roles]


@router.post(
    "/api/roles", response_model=RoleResponse, status_code=status.HTTP_201_CREATED
)
async def create_role(
    body: RoleCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin)),
):
    """Crea un rol personalizado."""
    existing = (
        await db.execute(select(Role).where(Role.name == body.name))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un rol con el nombre '{body.name}'",
        )

    role = Role(
        name=body.name,
        description=body.description,
        permissions=body.permissions,
        is_system=False,
    )
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return await _role_with_counts(db, role)


@router.patch("/api/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: uuid.UUID,
    body: RoleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin)),
):
    """Edita un rol. Los roles del sistema (admin, instructor) son inmutables."""
    role = (
        await db.execute(select(Role).where(Role.id == role_id))
    ).scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Rol no encontrado")
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"El rol '{role.name}' es del sistema y no puede modificarse",
        )

    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in updates and updates["name"] != role.name:
        clash = (
            await db.execute(select(Role).where(Role.name == updates["name"]))
        ).scalar_one_or_none()
        if clash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe un rol con el nombre '{updates['name']}'",
            )
    for field, value in updates.items():
        setattr(role, field, value)
    await db.commit()
    await db.refresh(role)
    return await _role_with_counts(db, role)


@router.delete("/api/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin)),
):
    """Elimina un rol personalizado (los del sistema no se pueden borrar)."""
    role = (
        await db.execute(select(Role).where(Role.id == role_id))
    ).scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Rol no encontrado")
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"El rol '{role.name}' es del sistema y no puede eliminarse",
        )
    await db.delete(role)
    await db.commit()


# ── HU-30: Asignación de rol con auditoría ───────────────────────────────────


@router.patch("/api/users/{user_id}/role", response_model=UserProfileResponse)
async def assign_user_role(
    user_id: uuid.UUID,
    body: AssignRoleRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_role(UserRole.admin)),
):
    """Cambia el rol de un usuario dejando registro de auditoría.

    Un administrador NO puede cambiar su propio rol (evita que el último
    admin se degrade a sí mismo y deje el sistema sin administración).
    """
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes modificar tu propio rol",
        )

    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    old_role = user.role
    if old_role == body.role:
        return user

    user.role = body.role

    # Auditoría: quién cambió, a quién, de qué rol a cuál y cuándo
    audit = DocumentHistory(
        doc_id=None,
        action=ROLE_CHANGE_ACTION,
        performed_by=current_admin.id,
        before_content={"user_id": str(user_id), "role": old_role.value},
        after_content={
            "user_id": str(user_id),
            "email": user.email,
            "role": body.role.value,
        },
        reason=(
            f"Rol de {user.email} cambiado de '{old_role.value}' "
            f"a '{body.role.value}' por {current_admin.email}"
        ),
    )
    db.add(audit)
    await db.commit()
    await db.refresh(user)

    logger.info(
        "🔐 Rol cambiado: %s %s → %s (por %s)",
        user.email,
        old_role.value,
        body.role.value,
        current_admin.email,
    )
    return user


@router.get("/api/users/role-audit", response_model=list[RoleChangeAuditEntry])
async def get_role_audit(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin)),
):
    """Historial de cambios de rol (auditoría de seguridad)."""
    limit = max(1, min(limit, 200))
    rows = (
        await db.execute(
            select(DocumentHistory)
            .where(DocumentHistory.action == ROLE_CHANGE_ACTION)
            .order_by(DocumentHistory.timestamp.desc())
            .limit(limit)
        )
    ).scalars()
    return list(rows)
