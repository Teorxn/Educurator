import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "educurator_theme";

interface ThemeContextValue {
  /** Lo que eligió el usuario (puede ser "system"). */
  preference: ThemePreference;
  /** El tema realmente aplicado tras resolver "system". */
  resolved: ResolvedTheme;
  setPreference: (p: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readPreference(): ThemePreference {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === "light" || stored === "dark" || stored === "system"
    ? stored
    : "system";
}

function systemTheme(): ResolvedTheme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function applyTheme(resolved: ResolvedTheme) {
  const root = document.documentElement;
  root.classList.toggle("dark", resolved === "dark");
  // Mantiene una única fuente de verdad del tema (ver comentario en index.css).
  // Además de la clase, `color-scheme` hace que el navegador pinte con el tema
  // correcto lo que no controlamos: barras de scroll y controles nativos.
  root.style.colorScheme = resolved;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readPreference);
  const [systemIsDark, setSystemIsDark] = useState(() => systemTheme() === "dark");

  // El tema aplicado se DERIVA en el render; guardarlo en su propio estado y
  // sincronizarlo desde un efecto provocaba un render en cascada por cada
  // cambio de tema.
  const resolved: ResolvedTheme =
    preference === "system" ? (systemIsDark ? "dark" : "light") : preference;

  useEffect(() => {
    applyTheme(resolved);
  }, [resolved]);

  // Con preferencia "system" el tema sigue al sistema operativo en vivo, sin
  // recargar; con una elección explícita el usuario manda y se ignora.
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => setSystemIsDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const setPreference = useCallback((p: ThemePreference) => {
    localStorage.setItem(STORAGE_KEY, p);
    setPreferenceState(p);
  }, []);

  return (
    <ThemeContext.Provider value={{ preference, resolved, setPreference }}>
      {children}
    </ThemeContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme debe usarse dentro de <ThemeProvider>");
  return ctx;
}
