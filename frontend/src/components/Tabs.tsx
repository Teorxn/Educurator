import type { LucideIcon } from "lucide-react";

export interface TabItem<T extends string> {
  id: T;
  label: string;
  icon?: LucideIcon;
  /** Cifra entre paréntesis a la derecha de la etiqueta. */
  count?: number;
  /** Ancla para el recorrido guiado (ver `TutorialModal`). */
  tour?: string;
}

interface TabsProps<T extends string> {
  items: readonly TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  /** Rótulo del grupo para lectores de pantalla. */
  label: string;
  /** `sm` para barras de filtros; `md` para la navegación de un módulo. */
  size?: "sm" | "md";
  className?: string;
}

/**
 * Grupo de pestañas segmentado: una sola forma para toda la aplicación, de modo
 * que cambiar de vista se lea igual en Documentos, Revisión o el detalle de un
 * documento.
 */
export default function Tabs<T extends string>({
  items,
  value,
  onChange,
  label,
  size = "md",
  className = "",
}: TabsProps<T>) {
  const pad =
    size === "sm" ? "px-3 py-1.5 text-xs" : "px-4 py-1.5 text-sm";

  return (
    <div
      role="tablist"
      aria-label={label}
      className={`flex w-fit items-center gap-1 rounded-full border border-line bg-surface-2 p-1 ${className}`}
    >
      {items.map(({ id, label: text, icon: Icon, count, tour }) => (
        <button
          key={id}
          role="tab"
          aria-selected={value === id}
          data-tour={tour}
          onClick={() => onChange(id)}
          className={`flex items-center gap-2 rounded-full font-semibold whitespace-nowrap transition-colors ${pad} ${
            value === id
              ? "bg-surface text-ink shadow-sm"
              : "text-ink-2 hover:text-ink"
          }`}
        >
          {Icon && <Icon className="h-4 w-4 shrink-0" />}
          {text}
          {count != null && <span className="tnum text-ink-3">({count})</span>}
        </button>
      ))}
    </div>
  );
}
