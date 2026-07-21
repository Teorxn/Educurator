import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { LogOut, User, Menu, HelpCircle } from "lucide-react";
import TutorialModal, { hasSeenTutorial } from "./TutorialModal";
import { getMyProfile } from "../api/account";

const TITLES: Record<string, string> = {
  "/dashboard": "Inicio",
  "/upload": "Subir documento",
  "/docs": "Documentos",
  "/review": "Revisión de sugerencias",
  "/chat": "Preguntar a mis documentos",
  "/logs": "Logs del agente",
  "/agent-runs": "Ejecuciones del agente",
  "/analytics": "Analytics",
  "/reference-docs": "Documentos de referencia",
  "/admin/users": "Administración de usuarios",
};

function deriveTitle(pathname: string): string {
  // Check exact match first
  if (TITLES[pathname]) return TITLES[pathname];
  // Dynamic routes
  if (pathname.startsWith("/docs/")) return "Detalle del documento";
  return "Dashboard";
}

interface HeaderProps {
  onMenuClick: () => void;
}

export default function Header({ onMenuClick }: HeaderProps) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const title = deriveTitle(pathname);

  // HU-21 — tutorial accesible desde cualquier sección; se abre solo la
  // primera vez y recuerda si el usuario ya lo vio.
  const [tutorialOpen, setTutorialOpen] = useState(false);
  const [displayName, setDisplayName] = useState("Instructor");

  useEffect(() => {
    if (!hasSeenTutorial()) setTutorialOpen(true);
    getMyProfile()
      .then(({ data }) => setDisplayName(data.full_name || data.email))
      .catch(() => {});
  }, []);

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
        {/* HU-21 — acceso al tutorial desde cualquier sección */}
        <button
          onClick={() => setTutorialOpen(true)}
          title="Ver tutorial de uso"
          aria-label="Ver tutorial de uso"
          className="p-1.5 rounded-md hover:bg-gray-100 text-gray-400 hover:text-violet-600 transition-colors"
        >
          <HelpCircle className="w-4 h-4" />
        </button>
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <div className="w-7 h-7 rounded-full bg-violet-100 flex items-center justify-center">
            <User className="w-3.5 h-3.5 text-violet-600" />
          </div>
          <span className="hidden sm:block max-w-[12rem] truncate">
            {displayName}
          </span>
        </div>
        <button
          onClick={handleLogout}
          title="Cerrar sesión"
          className="p-1.5 rounded-md hover:bg-gray-100 text-gray-400 hover:text-gray-700 transition-colors"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>

      <TutorialModal
        open={tutorialOpen}
        onClose={() => setTutorialOpen(false)}
      />
    </header>
  );
}
