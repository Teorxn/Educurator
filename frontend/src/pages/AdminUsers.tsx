import { useEffect, useState } from "react";
import {
  Loader2,
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
      <div className="flex items-center justify-center h-64 text-gray-400 gap-2">
        <Loader2 className="w-5 h-5 animate-spin" />
        <span className="text-sm">Cargando administración...</span>
      </div>
    );
  }

  if (error && users.length === 0) {
    return (
      <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3">
        <AlertCircle className="w-4 h-4 shrink-0" />
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {notice && (
        <div className="flex items-center gap-2 bg-green-50 border border-green-200 text-green-700 text-sm rounded-xl px-4 py-3">
          <ShieldCheck className="w-4 h-4 shrink-0" />
          {notice}
        </div>
      )}
      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Usuarios */}
      <section className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-800">
            Usuarios ({users.length})
          </h2>
          <button
            onClick={toggleAudit}
            className="flex items-center gap-1.5 text-xs font-medium text-violet-600 hover:text-violet-700"
          >
            <History className="w-3.5 h-3.5" />
            {showAudit ? "Ocultar" : "Ver"} auditoría de roles
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="px-4 py-2.5 text-left font-medium text-gray-600">
                  Usuario
                </th>
                <th className="px-4 py-2.5 text-left font-medium text-gray-600">
                  Profesión
                </th>
                <th className="px-4 py-2.5 text-left font-medium text-gray-600">
                  Estado
                </th>
                <th className="px-4 py-2.5 text-left font-medium text-gray-600">
                  Rol
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {users.map((u) => (
                <tr key={u.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3">
                    <span className="block text-gray-800">
                      {u.full_name || "—"}
                    </span>
                    <span className="block text-xs text-gray-400">
                      {u.email}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {u.profession || "—"}
                  </td>
                  <td className="px-4 py-3">
                    {u.is_active ? (
                      <span className="text-xs text-green-700 bg-green-50 border border-green-200 px-2 py-0.5 rounded-full">
                        Activo
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-xs text-gray-600 bg-gray-100 border border-gray-200 px-2 py-0.5 rounded-full">
                        <UserX className="w-3 h-3" />
                        Inactivo
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {u.id === myId ? (
                      <span
                        className="text-xs text-gray-400"
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
                        className="border border-gray-200 rounded-lg px-2 py-1 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-violet-400"
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
        <section className="bg-white rounded-xl border border-gray-200 p-4">
          <h2 className="text-sm font-semibold text-gray-800 mb-3">
            Auditoría de cambios de rol
          </h2>
          {audit.length === 0 ? (
            <p className="text-sm text-gray-400">Sin cambios registrados</p>
          ) : (
            <ul className="space-y-2">
              {audit.map((a) => (
                <li
                  key={a.id}
                  className="text-xs text-gray-600 border border-gray-100 rounded-lg px-3 py-2"
                >
                  <span className="block">{a.reason}</span>
                  <span className="block text-gray-400 mt-0.5">
                    {fmtDate(a.timestamp)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* Roles */}
      <section className="bg-white rounded-xl border border-gray-200 p-4">
        <h2 className="text-sm font-semibold text-gray-800 mb-3">
          Roles del sistema
        </h2>

        <div className="space-y-2 mb-4">
          {roles.map((r) => (
            <div
              key={r.id}
              className="flex items-center justify-between gap-3 border border-gray-100 rounded-lg px-3 py-2"
            >
              <div className="min-w-0">
                <span className="text-sm text-gray-800">{r.name}</span>
                {r.is_system && (
                  <span className="ml-2 text-[11px] text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded-full">
                    sistema
                  </span>
                )}
                {r.description && (
                  <span className="block text-xs text-gray-400 truncate">
                    {r.description}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-xs text-gray-400">
                  {r.users_count} usuario{r.users_count !== 1 ? "s" : ""}
                </span>
                {!r.is_system && (
                  <button
                    onClick={() => handleDeleteRole(r)}
                    className="text-gray-400 hover:text-red-600"
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
            className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-violet-400"
          />
          <button
            onClick={handleCreateRole}
            disabled={!newRole.trim()}
            className="flex items-center gap-1.5 bg-violet-600 hover:bg-violet-700 disabled:bg-violet-300 text-white text-sm font-medium px-3 py-2 rounded-lg"
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
            className="fixed inset-0 bg-black/40"
            onClick={() => setConfirming(null)}
          />
          <div className="relative bg-white rounded-2xl shadow-xl max-w-sm w-full p-6 space-y-4 z-10">
            <h3 className="text-base font-semibold text-gray-900">
              Confirmar cambio de rol
            </h3>
            <p className="text-sm text-gray-600">
              ¿Asignar el rol <strong>{confirming.role}</strong> a{" "}
              <strong>{confirming.email}</strong>? El cambio tiene efecto
              inmediato y queda registrado en la auditoría.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setConfirming(null)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg"
              >
                Cancelar
              </button>
              <button
                onClick={applyRoleChange}
                className="px-4 py-2 text-sm font-medium text-white bg-violet-600 hover:bg-violet-700 rounded-lg"
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
