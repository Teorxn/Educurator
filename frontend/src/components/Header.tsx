import { useNavigate, useLocation } from "react-router-dom";
import { LogOut, User, Menu } from "lucide-react";

const TITLES: Record<string, string> = {
  "/upload": "Subir documento",
  "/docs": "Documentos",
  "/review": "Revisión de sugerencias",
  "/logs": "Logs del agente",
  "/analytics": "Analytics",
  "/reference-docs": "Documentos de referencia",
};

interface HeaderProps {
  onMenuClick: () => void;
}

export default function Header({ onMenuClick }: HeaderProps) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const title = TITLES[pathname] ?? "Dashboard";

  const handleLogout = () => {
    localStorage.removeItem("access_token");
    navigate("/login");
  };

  return (
    <header className="h-14 border-b border-gray-200 bg-white flex items-center justify-between px-4 sm:px-6 shrink-0">
      <div className="flex items-center gap-3">
        {/* Hamburger — only visible on mobile */}
        <button
          onClick={onMenuClick}
          className="sm:hidden p-1.5 rounded-md hover:bg-gray-100 text-gray-500 transition-colors"
          aria-label="Abrir menú"
        >
          <Menu className="w-5 h-5" />
        </button>
        <h1 className="text-base font-semibold text-gray-800">{title}</h1>
      </div>

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <div className="w-7 h-7 rounded-full bg-violet-100 flex items-center justify-center">
            <User className="w-3.5 h-3.5 text-violet-600" />
          </div>
          <span className="hidden sm:block">Instructor</span>
        </div>
        <button
          onClick={handleLogout}
          title="Cerrar sesión"
          className="p-1.5 rounded-md hover:bg-gray-100 text-gray-400 hover:text-gray-700 transition-colors"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
}
