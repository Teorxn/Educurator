import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { LogOut, Menu, HelpCircle } from "lucide-react";
import TutorialModal, { hasSeenTutorial } from "./TutorialModal";
import ThemeToggle from "./ThemeToggle";
import { useProfile, clearProfileCache } from "../useProfile";

const PAGES: Record<string, { title: string; subtitle: string }> = {
  "/dashboard": {
    title: "Inicio",
    subtitle: "Estado general de tu base de conocimiento",
  },
  "/docs": {
    title: "Documentos",
    subtitle: "Material del curso y corpus de referencia",
  },
  "/review": {
    title: "Revisión",
    subtitle: "Aprueba o rechaza lo que propone el agente",
  },
  "/chat": {
    title: "Preguntar",
    subtitle: "Respuestas fundamentadas en tus documentos",
  },
  "/agent-runs": {
    title: "Ejecuciones",
    subtitle: "Historial de corridas del agente de curación",
  },
  "/analytics": {
    title: "Métricas",
    subtitle: "Actividad, resultados y consumo de IA",
  },
  "/admin/users": {
    title: "Administración",
    subtitle: "Usuarios, roles y auditoría de accesos",
  },
};

function derivePage(pathname: string) {
  if (PAGES[pathname]) return PAGES[pathname];
  if (pathname.startsWith("/docs/"))
    return { title: "Documento", subtitle: "Contenido, fragmentos e historial" };
  return { title: "EduCurator", subtitle: "" };
}

interface HeaderProps {
  onMenuClick: () => void;
}

export default function Header({ onMenuClick }: HeaderProps) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { title, subtitle } = derivePage(pathname);
  const { profile } = useProfile();

  // HU-21 — tutorial accesible desde cualquier sección; se abre solo la
  // primera vez y recuerda si el usuario ya lo vio.
  const [tutorialOpen, setTutorialOpen] = useState(false);

  useEffect(() => {
    if (!hasSeenTutorial()) setTutorialOpen(true);
  }, []);

  const handleLogout = () => {
    localStorage.removeItem("access_token");
    clearProfileCache();
    navigate("/login");
  };

  const displayName = profile?.full_name || profile?.email || "Instructor";
  const initial = displayName.trim().charAt(0).toUpperCase() || "?";

  return (
    <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center justify-between gap-4 border-b border-line bg-canvas/85 px-4 backdrop-blur-md sm:px-6">
      <div className="flex min-w-0 items-center gap-3">
        <button
          onClick={onMenuClick}
          className="btn-icon sm:hidden"
          aria-label="Abrir menú"
        >
          <Menu className="h-5 w-5" />
        </button>
        <div className="min-w-0">
          <h1 className="font-display truncate text-lg leading-tight font-semibold text-ink">
            {title}
          </h1>
          {subtitle && (
            <p className="hidden truncate text-xs text-ink-3 sm:block">
              {subtitle}
            </p>
          )}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <ThemeToggle />

        <button
          onClick={() => setTutorialOpen(true)}
          title="Ver tutorial de uso"
          aria-label="Ver tutorial de uso"
          className="btn-icon"
        >
          <HelpCircle className="h-4 w-4" />
        </button>

        <div className="mx-1 hidden h-6 w-px bg-line sm:block" />

        <div className="flex items-center gap-2.5">
          <div
            aria-hidden
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-xs font-bold text-brand-soft-fg"
          >
            {initial}
          </div>
          <div className="hidden min-w-0 leading-tight sm:block">
            <p className="max-w-[11rem] truncate text-xs font-semibold text-ink">
              {displayName}
            </p>
            {profile && (
              <p className="text-[11px] text-ink-3">
                {profile.role === "admin" ? "Administrador" : "Docente"}
              </p>
            )}
          </div>
        </div>

        <button
          onClick={handleLogout}
          title="Cerrar sesión"
          aria-label="Cerrar sesión"
          className="btn-icon"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>

      <TutorialModal open={tutorialOpen} onClose={() => setTutorialOpen(false)} />
    </header>
  );
}
