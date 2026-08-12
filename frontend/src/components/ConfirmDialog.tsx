import { useId } from "react";
import type { ReactNode } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import Modal from "./Modal";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  /** Qué implica la acción; una o dos frases. */
  description?: ReactNode;
  /** Nombre de lo que se va a eliminar, destacado bajo la descripción. */
  itemName?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** `danger` para acciones destructivas; `brand` para el resto. */
  tone?: "danger" | "brand";
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Confirmación de acciones irreversibles. Sustituye a los micro-botones «Sí/No»
 * que aparecían dentro de la fila: la acción es destructiva, así que interrumpe
 * y pide una decisión explícita en lugar de quedar a un clic de distancia.
 */
export default function ConfirmDialog({
  open,
  title,
  description,
  itemName,
  confirmLabel = "Eliminar",
  cancelLabel = "Cancelar",
  tone = "danger",
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const titleId = useId();

  return (
    <Modal
      open={open}
      onClose={loading ? () => {} : onCancel}
      labelledBy={titleId}
      size="sm"
    >
      <div className="p-5">
        <div className="flex items-start gap-3">
          <span
            className={`shrink-0 rounded-xl p-2 ${
              tone === "danger"
                ? "bg-danger-soft text-danger-fg"
                : "bg-brand-soft text-brand-soft-fg"
            }`}
          >
            <AlertTriangle className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <h2 id={titleId} className="text-base font-semibold text-ink">
              {title}
            </h2>
            {description && (
              <p className="mt-1 text-sm leading-relaxed text-ink-2">
                {description}
              </p>
            )}
          </div>
        </div>

        {itemName && (
          <p className="mt-3 truncate rounded-field bg-surface-2 px-3 py-2 text-sm font-medium text-ink">
            {itemName}
          </p>
        )}
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-line bg-surface-2 px-5 py-3">
        <button
          onClick={onCancel}
          disabled={loading}
          className="btn btn-secondary btn-sm"
          autoFocus
        >
          {cancelLabel}
        </button>
        <button
          onClick={onConfirm}
          disabled={loading}
          className={`btn btn-sm ${tone === "danger" ? "btn-danger" : "btn-primary"}`}
        >
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
