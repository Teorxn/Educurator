import { NavLink } from "react-router-dom";
import {
  FileText,
  CheckSquare,
  BarChart3,
  Activity,
  LayoutDashboard,
  MessageSquare,
  Shield,
  X,
} from "lucide-react";
import { useProfile } from "../useProfile";

interface NavItem {
  to: string;
  icon: typeof LayoutDashboard;
  label: string;
  /** Sólo visible para administradores. */
  adminOnly?: boolean;
  /** Ancla para el recorrido guiado (ver `TutorialModal`). */
  tour?: string;
}

interface NavGroup {
  title?: string;
  items: NavItem[];
}

// Agrupado por intención: primero el resumen, luego el trabajo diario del
// docente, y al final lo que se consulta de vez en cuando.
const NAV: NavGroup[] = [
  {
    items: [{ to: "/dashboard", icon: LayoutDashboard, label: "Inicio" }],
  },
  {
    title: "Curación",
    items: [
      { to: "/docs", icon: FileText, label: "Documentos", tour: "nav-docs" },
      { to: "/review", icon: CheckSquare, label: "Revisión" },
      { to: "/chat", icon: MessageSquare, label: "Preguntar" },
    ],
  },
  {
    title: "Seguimiento",
    items: [
      { to: "/agent-runs", icon: Activity, label: "Ejecuciones" },
      { to: "/analytics", icon: BarChart3, label: "Métricas", tour: "nav-analytics" },
      { to: "/admin/users", icon: Shield, label: "Administración", adminOnly: true },
    ],
  },
];

interface SidebarProps {
  onClose?: () => void;
}

export default function Sidebar({ onClose }: SidebarProps) {
  const { isAdmin } = useProfile();

  return (
    <aside className="flex h-full min-h-screen w-64 flex-col border-r border-line bg-surface">
      {/* Marca */}
      <div className="flex items-center justify-between gap-2 px-5 py-5">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand">
            <img
              src="/Softserve.png"
              alt=""
              className="h-5 w-5 object-contain"
            />
          </div>
          <div className="min-w-0">
            <p className="font-display text-[15px] leading-none font-semibold text-ink">
              EduCurator
            </p>
            <p className="mt-1 text-[11px] leading-none text-ink-3">
              Curación de conocimiento
            </p>
          </div>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="btn-icon sm:hidden"
            aria-label="Cerrar menú"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Navegación */}
      <nav className="flex-1 space-y-6 overflow-y-auto px-3 pb-4">
        {NAV.map((group, gi) => {
          const items = group.items.filter((it) => !it.adminOnly || isAdmin);
          if (items.length === 0) return null;
          return (
            <div key={group.title ?? gi}>
              {group.title && (
                <p className="mb-1.5 px-3 text-[10px] font-bold tracking-[0.1em] text-ink-3 uppercase">
                  {group.title}
                </p>
              )}
              <div className="space-y-0.5">
                {items.map(({ to, icon: Icon, label, tour }) => (
                  <NavLink
                    key={to}
                    to={to}
                    data-tour={tour}
                    onClick={onClose}
                    className={({ isActive }) =>
                      `relative flex items-center gap-3 rounded-field px-3 py-2 text-sm font-medium transition-colors ${
                        isActive
                          ? "bg-brand-soft text-brand-soft-fg"
                          : "text-ink-2 hover:bg-surface-2 hover:text-ink"
                      }`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        {/* Indicador de sección activa: refuerza el estado sin
                            depender sólo del color de fondo. */}
                        <span
                          aria-hidden
                          className={`absolute top-1/2 left-0 h-5 w-0.5 -translate-y-1/2 rounded-r-full bg-brand transition-opacity ${
                            isActive ? "opacity-100" : "opacity-0"
                          }`}
                        />
                        <Icon className="h-4 w-4 shrink-0" />
                        {label}
                      </>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          );
        })}
      </nav>

      <div className="border-t border-line px-5 py-4">
        <p className="text-[11px] text-ink-3">SoftServe University · 2025</p>
      </div>
    </aside>
  );
}
