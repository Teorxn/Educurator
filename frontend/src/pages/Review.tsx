import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  CheckCircle2,
  XCircle,
  AlertCircle,
  Loader2,
  X,
  FileText,
  ChevronDown,
  ChevronUp,
  ScrollText,
  Copy,
  TriangleAlert,
  HelpCircle,
  RefreshCw,
  BookOpen,
  Globe,
  PartyPopper,
  Inbox,
} from "lucide-react";
import {
  getSuggestions,
  approveSuggestion,
  rejectSuggestion,
  getDocs,
} from "../api/docs";
import type { Suggestion, Document } from "../api/docs";
import SuggestionModal from "../components/SuggestionModal";
import Tabs from "../components/Tabs";
import Skeleton, { LoadingLabel } from "../components/Skeleton";

/** Presentación por tipo: icono + tono. El color nunca informa por sí solo. */
const TYPE_UI: Record<
  string,
  { label: string; tone: string; icon: typeof Copy; hint: string }
> = {
  redundancy: {
    label: "Redundancia",
    tone: "chip-warning",
    icon: Copy,
    hint: "Contenido que se repite en varios lugares",
  },
  conflict: {
    label: "Conflicto",
    tone: "chip-danger",
    icon: TriangleAlert,
    hint: "Dos fragmentos que se contradicen",
  },
  inconsistency: {
    label: "Inconsistencia",
    tone: "chip-warning",
    icon: TriangleAlert,
    hint: "Datos que no concuerdan entre sí",
  },
  faq: {
    label: "FAQ",
    tone: "chip-info",
    icon: HelpCircle,
    hint: "Pregunta frecuente propuesta a partir del material",
  },
  update: {
    label: "Actualización",
    tone: "chip-brand",
    icon: RefreshCw,
    hint: "Contenido que podría estar desactualizado",
  },
};

const STATUS_TABS = [
  { id: "pending", label: "Por revisar" },
  { id: "approved", label: "Aprobadas" },
  { id: "rejected", label: "Rechazadas" },
  { id: "", label: "Todas" },
];

const TYPE_OPTIONS = [
  { value: "", label: "Todos los tipos" },
  { value: "redundancy", label: "Redundancia" },
  { value: "conflict", label: "Conflicto" },
  { value: "inconsistency", label: "Inconsistencia" },
  { value: "faq", label: "FAQ" },
  { value: "update", label: "Actualización" },
];

function fmtDate(d: string) {
  return new Intl.DateTimeFormat("es", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(d));
}

/** Agrupa por documento conservando el orden de llegada. */
function groupByDocument(items: Suggestion[]) {
  const groups = new Map<string, { name: string; items: Suggestion[] }>();
  for (const s of items) {
    const key = s.document_id;
    if (!groups.has(key)) {
      groups.set(key, { name: s.document_name || "Documento sin nombre", items: [] });
    }
    groups.get(key)!.items.push(s);
  }
  return Array.from(groups.entries()).map(([id, g]) => ({ id, ...g }));
}

export default function Review() {
  const [searchParams, setSearchParams] = useSearchParams();

  const statusFilter = searchParams.get("status") ?? "pending";
  const typeFilter = searchParams.get("type") ?? "";
  // HU-24: la redirección automática llega con ?document_id=…; se acepta
  // también ?doc_id= por compatibilidad con enlaces previos.
  const docFilter =
    searchParams.get("document_id") ?? searchParams.get("doc_id") ?? "";
  // HU-28: paginación
  const page = Math.max(1, Number(searchParams.get("page") ?? "1") || 1);
  const pageSize = Math.max(1, Number(searchParams.get("limit") ?? "25") || 25);

  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [total, setTotal] = useState(0);
  // Totales globales para la barra de progreso (independientes del filtro).
  const [pendingTotal, setPendingTotal] = useState(0);
  const [allTotal, setAllTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [rejectModal, setRejectModal] = useState<{ id: string; open: boolean }>({
    id: "",
    open: false,
  });
  const [selectedSuggestion, setSelectedSuggestion] = useState<Suggestion | null>(
    null,
  );
  const [rejectReason, setRejectReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [actionLoading, setActionLoading] = useState<
    Record<string, "approve" | "reject" | null>
  >({});
  const [expandedEvidence, setExpandedEvidence] = useState<
    Record<string, boolean>
  >({});

  // ── Documentos para el selector ─────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    getDocs()
      .then(({ data }) => {
        if (!cancelled) setDocuments(data.items);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Totales globales para el progreso ───────────────────────────────────
  const refreshTotals = () => {
    getSuggestions({ status: "pending", limit: 1 })
      .then(({ data }) => setPendingTotal(data.total))
      .catch(() => {});
    getSuggestions({ limit: 1 })
      .then(({ data }) => setAllTotal(data.total))
      .catch(() => {});
  };

  useEffect(refreshTotals, []);

  // ── Sugerencias del filtro activo ───────────────────────────────────────
  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      try {
        const params: Record<string, string | number> = { page, limit: pageSize };
        if (statusFilter) params.status = statusFilter;
        if (typeFilter) params.type = typeFilter;
        if (docFilter) params.document_id = docFilter;
        const { data } = await getSuggestions(params);
        if (!cancelled) {
          setSuggestions(data.items);
          setTotal(data.total);
        }
      } catch {
        // silent
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    return () => {
      cancelled = true;
    };
  }, [statusFilter, typeFilter, docFilter, page, pageSize]);

  // ── Filtros en la URL ───────────────────────────────────────────────────
  const setFilter = (key: string, value: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) next.set(key, value);
      else next.delete(key);
      // Cambiar un filtro reinicia la paginación (HU-28)
      if (key !== "page") next.delete("page");
      return next;
    });
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const goToPage = (p: number) => {
    const target = Math.min(Math.max(1, p), totalPages);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("page", String(target));
      return next;
    });
  };

  // ── Acciones ────────────────────────────────────────────────────────────
  const handleApprove = async (id: string) => {
    setActionLoading((p) => ({ ...p, [id]: "approve" }));
    try {
      await approveSuggestion(id);
      setSuggestions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, status: "approved" as const } : s)),
      );
      refreshTotals();
    } catch {
      // silent
    } finally {
      setActionLoading((p) => ({ ...p, [id]: null }));
    }
  };

  const handleReject = async () => {
    if (!rejectReason.trim()) return;
    setRejecting(true);
    const id = rejectModal.id;
    try {
      await rejectSuggestion(id, rejectReason);
      setSuggestions((prev) =>
        prev.map((s) =>
          s.id === id
            ? { ...s, status: "rejected" as const, review_reason: rejectReason }
            : s,
        ),
      );
      setRejectModal({ id: "", open: false });
      setRejectReason("");
      refreshTotals();
    } catch {
      // silent
    } finally {
      setRejecting(false);
    }
  };

  const reviewed = Math.max(0, allTotal - pendingTotal);
  const progress = allTotal > 0 ? Math.round((reviewed / allTotal) * 100) : 0;
  const groups = groupByDocument(suggestions);

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      {/* ── Progreso: responde "¿cuánto me queda?" de un vistazo ──────────── */}
      <section className="card p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-display text-lg font-semibold text-ink">
              {pendingTotal === 0
                ? "No tienes nada pendiente"
                : `${pendingTotal} sugerencia${pendingTotal !== 1 ? "s" : ""} por revisar`}
            </h2>
            <p className="mt-0.5 text-sm text-ink-2">
              {pendingTotal === 0
                ? "El agente no ha propuesto cambios nuevos."
                : "Aprueba lo que sea correcto y rechaza lo demás indicando por qué."}
            </p>
          </div>
          <div className="text-right">
            <p className="tnum text-2xl leading-none font-semibold text-ink">
              {progress}%
            </p>
            <p className="mt-1 text-xs text-ink-3">
              {reviewed} de {allTotal} revisadas
            </p>
          </div>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-chart-track">
          <div
            className="h-2 rounded-full bg-chart transition-[width] duration-500"
            style={{ width: `${progress}%` }}
            role="img"
            aria-label={`${reviewed} de ${allTotal} sugerencias revisadas`}
          />
        </div>
      </section>

      {/* ── Filtros: 1 grupo de pestañas + 2 selectores ───────────────────── */}
      <div data-tour="review-list" className="flex flex-wrap items-center gap-2">
        <Tabs
          items={STATUS_TABS}
          value={statusFilter}
          onChange={(id) => setFilter("status", id)}
          label="Estado de la sugerencia"
          size="sm"
        />

        <select
          value={typeFilter}
          onChange={(e) => setFilter("type", e.target.value)}
          aria-label="Filtrar por tipo"
          className="input w-auto py-1.5 text-xs"
        >
          {TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>

        <select
          value={docFilter}
          onChange={(e) => setFilter("doc_id", e.target.value)}
          aria-label="Filtrar por documento"
          className="input w-auto max-w-[16rem] py-1.5 text-xs"
        >
          <option value="">Todos los documentos</option>
          {documents.map((doc) => (
            <option key={doc.id} value={doc.id}>
              {doc.filename}
            </option>
          ))}
        </select>

        <span className="ml-auto text-xs text-ink-3">
          {total} resultado{total !== 1 ? "s" : ""}
        </span>
      </div>

      {/* ── Contenido ─────────────────────────────────────────────────────── */}
      {/* Sólo se vacía la lista cuando todavía no hay nada que enseñar. Al
          cambiar de filtro se mantiene el resultado anterior atenuado: antes
          la página se quedaba en blanco y volvía a crecer con cada filtro. */}
      {loading && suggestions.length === 0 ? (
        <div className="space-y-2" aria-hidden>
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="card space-y-3 p-4">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          ))}
          <LoadingLabel>Cargando sugerencias</LoadingLabel>
        </div>
      ) : suggestions.length === 0 ? (
        <div className="card flex flex-col items-center justify-center px-4 py-16 text-center">
          <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-success-soft">
            {statusFilter === "pending" ? (
              <PartyPopper className="h-6 w-6 text-success-fg" />
            ) : (
              <Inbox className="h-6 w-6 text-ink-3" />
            )}
          </span>
          <p className="font-medium text-ink">
            {statusFilter === "pending"
              ? "Todo revisado"
              : "No hay sugerencias que mostrar"}
          </p>
          <p className="mt-1 max-w-sm text-sm text-ink-2">
            {statusFilter === "pending"
              ? "No queda nada pendiente con estos filtros. El agente avisará cuando proponga algo nuevo."
              : "Prueba con otro estado, tipo o documento."}
          </p>
        </div>
      ) : (
        <div
          className={`space-y-5 transition-opacity duration-150 ${
            loading ? "pointer-events-none opacity-55" : "opacity-100"
          }`}
        >
          {groups.map((group) => {
            const groupPending = group.items.filter(
              (s) => s.status === "pending",
            ).length;
            return (
              <section key={group.id}>
                {/* Cabecera de documento: agrupar da contexto — "estas N son
                    del mismo material" — en vez de una lista plana. */}
                <div className="mb-2 flex items-center gap-2 px-1">
                  <FileText className="h-4 w-4 shrink-0 text-ink-3" />
                  <h3 className="min-w-0 truncate text-sm font-semibold text-ink">
                    {group.name}
                  </h3>
                  {groupPending > 0 && (
                    <span className="chip chip-warning shrink-0">
                      {groupPending} por revisar
                    </span>
                  )}
                  <a
                    href={`/docs/${group.id}`}
                    className="ml-auto shrink-0 text-xs font-semibold text-brand hover:text-brand-hover"
                  >
                    Ver documento
                  </a>
                </div>

                <div className="space-y-2">
                  {group.items.map((s) => {
                    const type = TYPE_UI[s.type] ?? TYPE_UI.redundancy;
                    const TypeIcon = type.icon;
                    const busy = actionLoading[s.id];
                    const isPending = s.status === "pending";

                    return (
                      <article
                        key={s.id}
                        className={`card p-4 transition-colors ${
                          isPending ? "" : "opacity-75"
                        }`}
                      >
                        {/* Meta compacta: tipo + señales, sin emoji */}
                        <div className="mb-2 flex flex-wrap items-center gap-1.5">
                          <span className={`chip ${type.tone}`} title={type.hint}>
                            <TypeIcon className="h-3 w-3" />
                            {type.label}
                          </span>

                          {!isPending && (
                            <span
                              className={`chip ${
                                s.status === "approved"
                                  ? "chip-success"
                                  : "chip-danger"
                              }`}
                            >
                              {s.status === "approved" ? (
                                <CheckCircle2 className="h-3 w-3" />
                              ) : (
                                <XCircle className="h-3 w-3" />
                              )}
                              {s.status === "approved" ? "Aprobada" : "Rechazada"}
                            </span>
                          )}

                          {s.source_type === "reference" && (
                            <span
                              className="chip chip-neutral"
                              title="Contrastada con un documento de referencia"
                            >
                              <BookOpen className="h-3 w-3" />
                              Referencia
                            </span>
                          )}

                          {s.source_web_url && (
                            <a
                              href={s.source_web_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="chip chip-info hover:brightness-95"
                              title="Apoyada en una fuente web"
                            >
                              <Globe className="h-3 w-3" />
                              Fuente web
                            </a>
                          )}

                          <span className="ml-auto text-xs text-ink-3">
                            Confianza {Math.round(s.confidence_score * 100)}%
                          </span>
                        </div>

                        {/* Propuesta */}
                        <button
                          onClick={() => setSelectedSuggestion(s)}
                          className="w-full text-left"
                        >
                          <p className="text-sm leading-relaxed text-ink">
                            {s.description}
                          </p>
                        </button>

                        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-3">
                          <span>{fmtDate(s.created_at)}</span>
                          <button
                            onClick={() => setSelectedSuggestion(s)}
                            className="font-medium text-brand hover:text-brand-hover"
                          >
                            Ver detalle
                          </button>
                          {s.source_chunks && s.source_chunks.length > 0 && (
                            <button
                              onClick={() =>
                                setExpandedEvidence((prev) => ({
                                  ...prev,
                                  [s.id]: !prev[s.id],
                                }))
                              }
                              className="flex items-center gap-1 font-medium text-brand hover:text-brand-hover"
                            >
                              <ScrollText className="h-3 w-3" />
                              {expandedEvidence[s.id] ? "Ocultar" : "Ver"} evidencia
                              {expandedEvidence[s.id] ? (
                                <ChevronUp className="h-3 w-3" />
                              ) : (
                                <ChevronDown className="h-3 w-3" />
                              )}
                            </button>
                          )}
                        </div>

                        {/* Evidencia, plegada por defecto */}
                        {expandedEvidence[s.id] && s.source_chunks && (
                          <div className="mt-2.5 space-y-2">
                            {s.source_chunks.map((chunk) => (
                              <div
                                key={chunk.chunk_id}
                                className="rounded-field border border-line bg-surface-2 p-3"
                              >
                                <div className="mb-1.5 flex items-center justify-between gap-2">
                                  <span className="text-xs font-medium text-ink-2">
                                    Fragmento #{chunk.chunk_index}
                                  </span>
                                  <span className="tnum text-xs text-ink-3">
                                    {chunk.token_count} tokens
                                    {chunk.page_number != null &&
                                      ` · pág. ${chunk.page_number}`}
                                  </span>
                                </div>
                                <p className="text-xs leading-relaxed whitespace-pre-wrap text-ink-2">
                                  {chunk.content}
                                </p>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Motivo del rechazo */}
                        {s.status === "rejected" && s.review_reason && (
                          <div className="note note-danger mt-2.5 text-xs">
                            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                            <span>{s.review_reason}</span>
                          </div>
                        )}

                        {/* Acciones: son la tarea principal, así que van con
                            etiqueta y tamaño completo, no como iconos sueltos. */}
                        {isPending ? (
                          <div className="mt-3 flex items-center gap-2 border-t border-line pt-3">
                            <button
                              onClick={() => handleApprove(s.id)}
                              disabled={!!busy}
                              className="btn btn-success btn-sm"
                            >
                              {busy === "approve" ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <CheckCircle2 className="h-3.5 w-3.5" />
                              )}
                              Aprobar
                            </button>
                            <button
                              onClick={() => {
                                setRejectModal({ id: s.id, open: true });
                                setRejectReason("");
                              }}
                              disabled={!!busy}
                              className="btn btn-secondary btn-sm"
                            >
                              <XCircle className="h-3.5 w-3.5" />
                              Rechazar
                            </button>
                          </div>
                        ) : (
                          (s.reviewed_by_name ||
                            s.reviewed_by_email ||
                            s.reviewed_at) && (
                            <p className="mt-2.5 border-t border-line pt-2.5 text-xs text-ink-3">
                              Revisada
                              {(s.reviewed_by_name || s.reviewed_by_email) &&
                                ` por ${s.reviewed_by_name || s.reviewed_by_email}`}
                              {s.reviewed_at && ` · ${fmtDate(s.reviewed_at)}`}
                            </p>
                          )
                        )}
                      </article>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      )}

      {/* ── HU-28: paginación ─────────────────────────────────────────────── */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-1">
          <button
            onClick={() => goToPage(page - 1)}
            disabled={page <= 1}
            className="btn btn-secondary btn-sm"
          >
            Anterior
          </button>
          <span className="tnum px-2 text-xs text-ink-2">
            Página {page} de {totalPages}
          </span>
          <button
            onClick={() => goToPage(page + 1)}
            disabled={page >= totalPages}
            className="btn btn-secondary btn-sm"
          >
            Siguiente
          </button>
        </div>
      )}

      {/* ── Detalle ───────────────────────────────────────────────────────── */}
      {selectedSuggestion && (
        <SuggestionModal
          suggestion={selectedSuggestion}
          onClose={() => setSelectedSuggestion(null)}
        />
      )}

      {/* ── Rechazo ───────────────────────────────────────────────────────── */}
      {rejectModal.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-[2px]"
            onClick={() => setRejectModal({ id: "", open: false })}
          />
          <div className="relative z-10 w-full max-w-md space-y-4 rounded-2xl border border-line bg-surface p-6 shadow-[var(--shadow-overlay)]">
            <div className="flex items-center justify-between">
              <h3 className="font-display text-lg font-semibold text-ink">
                Rechazar sugerencia
              </h3>
              <button
                onClick={() => setRejectModal({ id: "", open: false })}
                className="btn-icon h-8 w-8"
                aria-label="Cerrar"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <p className="text-sm text-ink-2">
              El motivo queda registrado y ayuda al agente a no repetir el mismo
              tipo de propuesta.
            </p>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              rows={3}
              autoFocus
              aria-label="Motivo del rechazo"
              placeholder="Ej: no es relevante para el contenido del curso..."
              className="input resize-none"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setRejectModal({ id: "", open: false })}
                className="btn btn-secondary"
              >
                Cancelar
              </button>
              <button
                onClick={handleReject}
                disabled={!rejectReason.trim() || rejecting}
                className="btn btn-danger"
              >
                {rejecting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {rejecting ? "Rechazando..." : "Rechazar"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
