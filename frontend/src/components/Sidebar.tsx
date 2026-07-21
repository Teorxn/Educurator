import { NavLink } from "react-router-dom";
import {
  Upload,
  FileText,
  CheckSquare,
  BarChart3,
  BookOpen,
  Activity,
  LayoutDashboard,
  MessageSquare,
  Shield,
  X,
} from "lucide-react";

const NAV = [
  { to: "/dashboard", icon: LayoutDashboard, label: "Inicio" },
  { to: "/upload", icon: Upload, label: "Subir documento" },
  { to: "/docs", icon: FileText, label: "Documentos" },
  { to: "/reference-docs", icon: BookOpen, label: "Documentos de referencia" },
  { to: "/review", icon: CheckSquare, label: "Revisión" },
  { to: "/chat", icon: MessageSquare, label: "Preguntar" },
  { to: "/agent-runs", icon: Activity, label: "Ejecuciones del agente" },
  { to: "/analytics", icon: BarChart3, label: "Analytics" },
  { to: "/admin/users", icon: Shield, label: "Administración" },
];

interface SidebarProps {
  onClose?: () => void;
}

export default function Sidebar({ onClose }: SidebarProps) {
  return (
    <aside className="w-60 h-full min-h-screen bg-slate-900 flex flex-col">
      {/* Logo + mobile close button */}
      <div className="flex items-center justify-between px-5 py-5 border-b border-slate-700/60">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 bg-slate-700 rounded-lg flex items-center justify-center shadow-sm">
            <img
              src="/Softserve.png"
              alt="SoftServe"
              className="w-5 h-5 object-contain"
            />
          </div>
          <div>
            <p className="text-white font-semibold text-sm leading-none">
              EduCurator AI
            </p>
            <p className="text-slate-500 text-xs mt-0.5">
              Curación de conocimiento
            </p>
          </div>
        </div>
        {/* Close button only on mobile */}
        {onClose && (
          <button
            onClick={onClose}
            className="sm:hidden p-1 rounded-md text-slate-400 hover:text-slate-200 transition-colors"
            aria-label="Cerrar menú"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            onClick={onClose}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? "bg-violet-600 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-100 hover:bg-slate-800"
              }`
            }
          >
            <Icon className="w-4 h-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-4 py-4 border-t border-slate-700/60">
        <p className="text-xs text-slate-600">SoftServe University · 2025</p>
      </div>
    </aside>
  );
}
