import { useEffect } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

const SIZES = {
  sm: "max-w-sm",
  md: "max-w-lg",
  lg: "max-w-2xl",
  xl: "max-w-5xl",
} as const;

interface ModalProps {
  open: boolean;
  onClose: () => void;
  /** `id` del título del panel, para enlazarlo con `aria-labelledby`. */
  labelledBy?: string;
  size?: keyof typeof SIZES;
  children: ReactNode;
}

/**
 * Capa base de todos los diálogos: fondo, panel centrado, cierre con Escape y
 * bloqueo del scroll de la página.
 *
 * Va montado en `document.body` mediante un portal, no donde se declara: un
 * ancestro con `filter`, `backdrop-filter` o `transform` se convierte en el
 * bloque contenedor de sus descendientes `fixed`, así que un modal declarado
 * dentro (por ejemplo, en la cabecera, que lleva `backdrop-blur`) se
 * posicionaría respecto a esa caja de 64 px en vez del viewport.
 */
export default function Modal({
  open,
  onClose,
  labelledBy,
  size = "md",
  children,
}: ModalProps) {
  useEffect(() => {
    if (!open) return;

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="anim-fade-in fixed inset-0 bg-black/50 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        className={`anim-rise-in relative z-10 max-h-[90vh] w-full overflow-y-auto rounded-2xl border border-line bg-surface shadow-[var(--shadow-overlay)] ${SIZES[size]}`}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
