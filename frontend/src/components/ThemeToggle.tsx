import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "../theme";
import type { ThemePreference } from "../theme";

const OPTIONS: {
  value: ThemePreference;
  icon: typeof Sun;
  label: string;
}[] = [
  { value: "light", icon: Sun, label: "Tema claro" },
  { value: "dark", icon: Moon, label: "Tema oscuro" },
  { value: "system", icon: Monitor, label: "Seguir al sistema" },
];

/** Selector segmentado de tema: claro / oscuro / sistema. */
export default function ThemeToggle() {
  const { preference, setPreference } = useTheme();

  return (
    <div
      role="radiogroup"
      aria-label="Tema de la interfaz"
      className="flex items-center gap-0.5 rounded-full border border-line bg-surface-2 p-0.5"
    >
      {OPTIONS.map(({ value, icon: Icon, label }) => {
        const active = preference === value;
        return (
          <button
            key={value}
            role="radio"
            aria-checked={active}
            aria-label={label}
            title={label}
            onClick={() => setPreference(value)}
            className={`flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
              active
                ? "bg-surface text-brand shadow-sm"
                : "text-ink-3 hover:text-ink"
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
          </button>
        );
      })}
    </div>
  );
}
