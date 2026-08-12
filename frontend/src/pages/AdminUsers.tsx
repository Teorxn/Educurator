import { useEffect, useState } from "react";
import {
  ShieldCheck,
  AlertCircle,
  UserX,
  History,
  Trash2,
  Plus,
} from "lucide-react";
import {
  assignUserRole,
  createRole,
  deleteRole,
  getMyProfile,
  getRoleAudit,
  listRoles,
  listUsers,
} from "../api/account";
import type { AdminUser, Role, RoleAuditEntry } from "../api/account";
import Skeleton, { SkeletonTable, LoadingLabel } from "../components/Skeleton";

function fmtDate(d: string) {
  return new Intl.DateTimeFormat("es", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(d));
}

/** HU-30 — Administración de usuarios y roles (solo admin). */
export default function AdminUsers() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [audit, setAudit] = useState<RoleAuditEntry[]>([]);
  const [myId, setMyId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showAudit, setShowAudit] = useState(false);
  const [newRole, setNewRole] = useState("");
  const [confirming, setConfirming] = useState<{
    userId: string;
    email: string;
    role: "instructor" | "admin";
  } | null>(null);

  const loadAll = async (first = false) => {
    try {
      const [u, r, me] = await Promise.all([
        listUsers(),
        listRoles(),
        getMyProfile(),
      ]);
      setUsers(u.data);
      setRoles(r.data);
      setMyId(me.data.id);
      setError("");
    } catch (e) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      setError(
        status === 403
          ? "Necesitas permisos de administrador para ver esta sección."
          : "No se pudieron cargar los datos de administración.",
      );
    } finally {
      if (first) setLoading(false);
    }
  };

  useEffect(() => {
    loadAll(true);
  }, []);

  const applyRoleChange = async () => {
    if (!confirming) return;
    const { userId, role, email } = confirming;
    setConfirming(null);
    try {
      await assignUserRole(userId, role);
      setNotice(`Rol de ${email} actualizado a ${role}`);
      await loadAll();
      if (showAudit) {
        const { data } = await getRoleAudit();
        setAudit(data);
      }
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setError(detail || "No se pudo cambiar el rol.");
    }
  };

  const handleCreateRole = async () => {
    const name = newRole.trim().toLowerCase();
    if (!name) return;
    try {
      await createRole({ name });
      setNewRole("");
      setNotice(`Rol '${name}' creado`);
      await loadAll();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setError(detail || "No se pudo crear el rol.");
    }
  };

  const handleDeleteRole = async (role: Role) => {
    try {
      await deleteRole(role.id);
      setNotice(`Rol '${role.name}' eliminado`);
      await loadAll();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setError(detail || "No se pudo eliminar el rol.");
    }
  };

  const toggleAudit = async () => {
    const next = !showAudit;
    setShowAudit(next);
    if (next) {
      try {
        const { data } = await getRoleAudit();
        setAudit(data);
      } catch {
        /* silencioso */
      }
    }
  };

  if (loading) {
    return (
      <div className="space-y-5">
        <LoadingLabel>Cargando administración</LoadingLabel>
        <div className="card overflow-hidden">
          <div className="border-b border-line px-5 py-4">
            <Skeleton className="h-4 w-40" />
          </div>
          <SkeletonTable rows={5} cols={["w-1/3", "w-24", "w-20", "w-16"]} />
        </div>
      </div>
    );
  }

  if (error && users.length === 0) {
    return (
      <div className="flex items-center gap-2 bg-danger-soft border border-transparent text-danger-fg text-sm rounded-xl px-4 py-3">
        <AlertCircle className="w-4 h-4 shrink-0" />
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {notice && (
        <div className="flex items-center gap-2 bg-success-soft border border-transparent text-success-fg text-sm rounded-xl px-4 py-3">
          <ShieldCheck className="w-4 h-4 shrink-0" />
          {notice}
        </div>
      )}
      {error && (
        <div className="flex items-center gap-2 bg-danger-soft border border-transparent text-danger-fg text-sm rounded-xl px-4 py-3">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Usuarios */}
      <section className="card overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-line">
          <h2 className="text-sm font-semibold text-ink">
            Usuarios ({users.length})
          </h2>
          <button
            onClick={toggleAudit}
            className="flex items-center gap-1.5 text-xs font-medium text-brand hover:text-brand-hover"
          >
            <History className="w-3.5 h-3.5" />
            {showAudit ? "Ocultar" : "Ver"} auditoría de roles
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-2 border-b border-line">
              <tr>
                <th className="px-4 py-2.5 text-left font-medium text-ink-2">
                  Usuario
                </th>
                <th className="px-4 py-2.5 text-left font-medium text-ink-2">
                  Profesión
                </th>
                <th className="px-4 py-2.5 text-left font-medium text-ink-2">
                  Estado
                </th>
                <th className="px-4 py-2.5 text-left font-medium text-ink-2">
                  Rol
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {users.map((u) => (
                <tr key={u.id} className="hover:bg-surface-2 transition-colors">
                  <td className="px-4 py-3">
                    <span className="block text-ink">
                      {u.full_name || "—"}
                    </span>
                    <span className="block text-xs text-ink-3">
                      {u.email}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-ink-2 text-xs">
                    {u.profession || "—"}
                  </td>
                  <td className="px-4 py-3">
                    {u.is_active ? (
                      <span className="text-xs text-success-fg bg-success-soft border border-transparent px-2 py-0.5 rounded-full">
                        Activo
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-xs text-ink-2 bg-surface-2 border border-line px-2 py-0.5 rounded-full">
                        <UserX className="w-3 h-3" />
                        Inactivo
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {u.id === myId ? (
                      <span
                        className="text-xs text-ink-3"
                        title="No puedes modificar tu propio rol"
                      >
                        {u.role} (tú)
                      </span>
                    ) : (
                      <select
                        value={u.role}
                        onChange={(e) =>
                          setConfirming({
                            userId: u.id,
                            email: u.email,
                            role: e.target.value as "instructor" | "admin",
                          })
                        }
                        className="border border-line rounded-lg px-2 py-1 text-xs bg-surface focus:outline-none focus:ring-2 focus:ring-brand"
                      >
                        <option value="instructor">instructor</option>
                        <option value="admin">admin</option>
                      </select>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Auditoría de cambios de rol */}
      {showAudit && (
        <section className="card p-4">
          <h2 className="text-sm font-semibold text-ink mb-3">
            Auditoría de cambios de rol
          </h2>
          {audit.length === 0 ? (
            <p className="text-sm text-ink-3">Sin cambios registrados</p>
          ) : (
            <ul className="space-y-2">
              {audit.map((a) => (
                <li
                  key={a.id}
                  className="text-xs text-ink-2 border border-line rounded-lg px-3 py-2"
                >
                  <span className="block">{a.reason}</span>
                  <span className="block text-ink-3 mt-0.5">
                    {fmtDate(a.timestamp)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* Roles */}
      <section className="card p-4">
        <h2 className="text-sm font-semibold text-ink mb-3">
          Roles del sistema
        </h2>

        <div className="space-y-2 mb-4">
          {roles.map((r) => (
            <div
              key={r.id}
              className="flex items-center justify-between gap-3 border border-line rounded-lg px-3 py-2"
            >
              <div className="min-w-0">
                <span className="text-sm text-ink">{r.name}</span>
                {r.is_system && (
                  <span className="ml-2 text-[11px] text-ink-2 bg-surface-2 px-1.5 py-0.5 rounded-full">
                    sistema
                  </span>
                )}
                {r.description && (
                  <span className="block text-xs text-ink-3 truncate">
                    {r.description}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-xs text-ink-3">
                  {r.users_count} usuario{r.users_count !== 1 ? "s" : ""}
                </span>
                {!r.is_system && (
                  <button
                    onClick={() => handleDeleteRole(r)}
                    className="text-ink-3 hover:text-danger-fg"
                    aria-label={`Eliminar rol ${r.name}`}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="flex gap-2">
          <input
            value={newRole}
            onChange={(e) => setNewRole(e.target.value)}
            placeholder="nombre_del_rol (minúsculas)"
            className="flex-1 px-3 py-2 border border-line rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand"
          />
          <button
            onClick={handleCreateRole}
            disabled={!newRole.trim()}
            className="btn btn-primary"
          >
            <Plus className="w-4 h-4" />
            Crear rol
          </button>
        </div>
      </section>

      {/* Confirmación de cambio de rol */}
      {confirming && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-[2px]"
            onClick={() => setConfirming(null)}
          />
          <div className="relative bg-surface border border-line rounded-2xl shadow-[var(--shadow-overlay)] max-w-sm w-full p-6 space-y-4 z-10">
            <h3 className="text-base font-semibold text-ink">
              Confirmar cambio de rol
            </h3>
            <p className="text-sm text-ink-2">
              ¿Asignar el rol <strong>{confirming.role}</strong> a{" "}
              <strong>{confirming.email}</strong>? El cambio tiene efecto
              inmediato y queda registrado en la auditoría.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setConfirming(null)}
                className="btn btn-secondary"
              >
                Cancelar
              </button>
              <button
                onClick={applyRoleChange}
                className="btn btn-primary"
              >
                Confirmar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
