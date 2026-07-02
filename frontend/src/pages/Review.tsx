import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  CheckSquare,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Loader2,
  X,
  FileText,
  ChevronDown,
  ChevronUp,
  ScrollText,
} from "lucide-react";
import {
  getSuggestions,
  approveSuggestion,
  rejectSuggestion,
  getDocs,
} from "../api/docs";
import type { Suggestion, Document } from "../api/docs";
import SuggestionModal from "../components/SuggestionModal";

const TYPE_LABEL: Record<string, { label: string; color: string }> = {
  redundancy: {
    label: "Redundancia",
    color: "bg-amber-100 text-amber-800 border-amber-200",
  },
  conflict: {
    label: "Conflicto",
    color: "bg-red-100 text-red-800 border-red-200",
  },
  inconsistency: {
    label: "Inconsistencia",
    color: "bg-orange-100 text-orange-800 border-orange-200",
  },
  faq: { label: "FAQ", color: "bg-blue-100 text-blue-800 border-blue-200" },
  update: {
    label: "Actualización",
    color: "bg-purple-100 text-purple-800 border-purple-200",
  },
};

const STATUS_BADGE: Record<
  string,
  { label: string; color: string; dot: string }
> = {
  pending: {
    label: "Pendiente",
    color: "bg-yellow-50 text-yellow-700 border-yellow-200",
    dot: "bg-yellow-400",
  },
  approved: {
    label: "Aprobada",
    color: "bg-green-50 text-green-700 border-green-200",
    dot: "bg-green-500",
  },
  rejected: {
    label: "Rechazada",
    color: "bg-red-50 text-red-700 border-red-200",
    dot: "bg-red-500",
  },
};

const TYPE_OPTIONS = [
  { value: "", label: "Todos" },
  { value: "redundancy", label: "Redundancia" },
  { value: "conflict", label: "Conflicto" },
  { value: "inconsistency", label: "Inconsistencia" },
  { value: "faq", label: "FAQ" },
  { value: "update", label: "Actualización" },
];

const STATUS_OPTIONS = [
  { value: "pending", label: "Pendientes" },
  { value: "approved", label: "Aprobadas" },
  { value: "rejected", label: "Rechazadas" },
  { value: "", label: "Todas" },
];

function fmtDate(d: string) {
  return new Intl.DateTimeFormat("es", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(d));
}

function fmtConfidence(score: number) {
  return `${(score * 100).toFixed(0)}%`;
}

export default function Review() {
  const [searchParams, setSearchParams] = useSearchParams();

  const statusFilter = searchParams.get("status") ?? "pending";
  const typeFilter = searchParams.get("type") ?? "";
  const docFilter = searchParams.get("doc_id") ?? "";

  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [rejectModal, setRejectModal] = useState<{ id: string; open: boolean }>(
    { id: "", open: false },
  );
  const [selectedSuggestion, setSelectedSuggestion] =
    useState<Suggestion | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [actionLoading, setActionLoading] = useState<
    Record<string, "approve" | "reject" | null>
  >({});
  const [expandedEvidence, setExpandedEvidence] = useState<
    Record<string, boolean>
  >({});

  // ── Load documents for filter dropdown ──────────────────────────────────
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

  // ── Load suggestions ────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      try {
        const params: Record<string, string> = {};
        if (statusFilter) params.status = statusFilter;
        if (typeFilter) params.type = typeFilter;
        if (docFilter) params.document_id = docFilter;
        const { data } = await getSuggestions(params);
        if (!cancelled) setSuggestions(data.items);
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
  }, [statusFilter, typeFilter, docFilter]);

  // ── Update URL helpers ──────────────────────────────────────────────────
  const setFilter = (key: string, value: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) {
        next.set(key, value);
      } else {
        next.delete(key);
      }
      return next;
    });
  };

  // ── Actions ─────────────────────────────────────────────────────────────
  const handleApprove = async (id: string) => {
    setActionLoading((p) => ({ ...p, [id]: "approve" }));
    try {
      await approveSuggestion(id);
      setSuggestions((prev) =>
        prev.map((s) =>
          s.id === id ? { ...s, status: "approved" as const } : s,
        ),
      );
    } catch {
      // silent
    } finally {
      setActionLoading((p) => ({ ...p, [id]: null }));
    }
  };

  const openRejectModal = (id: string) => {
    setRejectModal({ id, open: true });
    setRejectReason("");
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
    } catch {
      // silent
    } finally {
      setRejecting(false);
    }
  };

  // ── Loading state ───────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400 gap-2">
        <Loader2 className="w-5 h-5 animate-spin" />
        <span className="text-sm">Cargando sugerencias...</span>
      </div>
    );
  }

  const pendingCount = suggestions.filter((s) => s.status === "pending").length;

  return (
    <div className="space-y-4">
      {/* ── Filters ──────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Status filter */}
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium text-gray-500 mr-1">
            Estado:
          </span>
          {STATUS_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setFilter("status", opt.value)}
              className={`text-xs font-medium px-3 py-1.5 rounded-full border transition-colors ${
                statusFilter === opt.value
                  ? "bg-violet-600 text-white border-violet-600"
                  : "bg-white text-gray-600 border-gray-200 hover:border-violet-300"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <div className="w-px h-6 bg-gray-200" />

        {/* Type filter */}
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium text-gray-500 mr-1">Tipo:</span>
          {TYPE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setFilter("type", opt.value)}
              className={`text-xs font-medium px-3 py-1.5 rounded-full border transition-colors ${
                typeFilter === opt.value
                  ? "bg-violet-600 text-white border-violet-600"
                  : "bg-white text-gray-600 border-gray-200 hover:border-violet-300"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <div className="w-px h-6 bg-gray-200" />

        {/* Document filter */}
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium text-gray-500 mr-1">
            Documento:
          </span>
          <select
            value={docFilter}
            onChange={(e) => setFilter("doc_id", e.target.value)}
            className="text-xs border border-gray-200 rounded-lg px-2.5 py-1.5 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-violet-400 focus:border-transparent"
          >
            <option value="">Todos los documentos</option>
            {documents.map((doc) => (
              <option key={doc.id} value={doc.id}>
                {doc.filename}
              </option>
            ))}
          </select>
        </div>

        {/* Count */}
        <p className="text-sm text-gray-500 ml-auto">
          {suggestions.length} sugerencia
          {suggestions.length !== 1 ? "s" : ""}
          {pendingCount > 0 && (
            <span className="text-yellow-600 ml-1">
              ({pendingCount} pendientes)
            </span>
          )}
        </p>
      </div>

      {/* ── Empty state ──────────────────────────────────────────────── */}
      {suggestions.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-center">
          <div className="w-14 h-14 bg-gray-100 rounded-2xl flex items-center justify-center mb-4">
            <CheckSquare className="w-7 h-7 text-gray-400" />
          </div>
          <p className="text-gray-600 font-medium">No hay sugerencias</p>
          <p className="text-sm text-gray-400 mt-1">
            No hay sugerencias con los filtros seleccionados
          </p>
        </div>
      ) : (
        /* ── Suggestions list ──────────────────────────────────────────── */
        <div className="space-y-3">
          {suggestions.map((s) => {
            const typeStyle = TYPE_LABEL[s.type] ?? TYPE_LABEL.redundancy;
            const statusStyle = STATUS_BADGE[s.status] ?? STATUS_BADGE.pending;
            const loading_action = actionLoading[s.id];

            return (
              <div
                key={s.id}
                className={`bg-white rounded-xl border p-4 transition-colors ${
                  s.status === "pending"
                    ? "border-gray-200 hover:border-violet-200"
                    : "border-gray-100"
                }`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    {/* Header row */}
                    <div className="flex items-center gap-2 mb-2 flex-wrap">
                      <span
                        className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${typeStyle.color}`}
                      >
                        {typeStyle.label}
                      </span>
                      {/* Severity badge for conflict/inconsistency types */}
                      {(s.type === "conflict" || s.type === "inconsistency") &&
                        s.confidence_score != null && (
                          <span
                            className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border ${
                              s.confidence_score >= 0.8
                                ? "bg-red-100 text-red-700 border-red-200"
                                : s.confidence_score >= 0.6
                                  ? "bg-yellow-100 text-yellow-700 border-yellow-200"
                                  : "bg-gray-100 text-gray-600 border-gray-200"
                            }`}
                          >
                            {s.confidence_score >= 0.8
                              ? "🔴 Alta"
                              : s.confidence_score >= 0.6
                                ? "🟡 Media"
                                : "⚪ Baja"}
                          </span>
                        )}
                      <span
                        className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border ${statusStyle.color}`}
                      >
                        <span
                          className={`w-1.5 h-1.5 rounded-full ${statusStyle.dot}`}
                        />
                        {statusStyle.label}
                      </span>
                      {s.document_name && (
                        <span className="flex items-center gap-1 text-xs text-gray-400">
                          <FileText className="w-3 h-3" />
                          {s.document_name}
                        </span>
                      )}
                      {s.source_type === "reference" && (
                        <span
                          className="inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-800 cursor-help"
                          title="Esta sugerencia usa un documento de referencia como fuente"
                        >
                          📚 Fuente: Referencia
                        </span>
                      )}
                      {s.source_web_url && (
                        <a
                          href={s.source_web_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-sky-100 text-sky-800 hover:bg-sky-200 transition-colors"
                          title="Esta sugerencia se apoya en una fuente web"
                        >
                          🌐 Fuente Web
                        </a>
                      )}
                      <span className="text-xs text-gray-400">
                        {fmtDate(s.created_at)}
                      </span>
                    </div>

                    {/* Description — clickable to open modal */}
                    <button
                      onClick={() => setSelectedSuggestion(s)}
                      className="text-left w-full"
                    >
                      <p className="text-sm text-gray-800 leading-relaxed">
                        {s.description}
                      </p>
                    </button>

                    {/* Confidence + Reasoning */}
                    <div className="flex items-center gap-3 mt-2">
                      <span className="text-xs font-medium text-violet-600 bg-violet-50 px-2 py-0.5 rounded-full">
                        Confianza: {fmtConfidence(s.confidence_score)}
                      </span>
                      {s.reasoning && (
                        <button
                          onClick={() => setSelectedSuggestion(s)}
                          className="flex items-center gap-1 text-xs text-gray-400 hover:text-violet-600 underline decoration-dotted"
                        >
                          <span>Ver razonamiento completo</span>
                        </button>
                      )}
                      {/* Botón Ver contexto completo para inconsistencias */}
                      {(s.type === "conflict" || s.type === "inconsistency") &&
                        s.source_chunks &&
                        s.source_chunks.length > 0 && (
                          <a
                            href={`/docs/${s.document_id}`}
                            className="flex items-center gap-1 text-xs text-gray-400 hover:text-blue-600 underline decoration-dotted"
                          >
                            <FileText className="w-3 h-3" />
                            <span>Ver contexto completo</span>
                          </a>
                        )}
                    </div>

                    {/* Evidence */}
                    {s.source_chunks && s.source_chunks.length > 0 && (
                      <div className="mt-3">
                        <button
                          onClick={() =>
                            setExpandedEvidence((prev) => ({
                              ...prev,
                              [s.id]: !prev[s.id],
                            }))
                          }
                          className="flex items-center gap-1.5 text-xs font-medium text-violet-600 hover:text-violet-700 transition-colors"
                        >
                          <ScrollText className="w-3.5 h-3.5" />
                          {expandedEvidence[s.id]
                            ? "Ocultar evidencia"
                            : `Ver evidencia (${s.source_chunks.length} chunk${s.source_chunks.length !== 1 ? "s" : ""})`}
                          {expandedEvidence[s.id] ? (
                            <ChevronUp className="w-3 h-3" />
                          ) : (
                            <ChevronDown className="w-3 h-3" />
                          )}
                        </button>

                        {expandedEvidence[s.id] && (
                          <div className="mt-2 space-y-2">
                            {s.source_chunks.map((chunk) => (
                              <div
                                key={chunk.chunk_id}
                                className="bg-gray-50 border border-gray-200 rounded-lg p-3"
                              >
                                <div className="flex items-center justify-between mb-1.5">
                                  <span className="text-xs font-medium text-gray-500">
                                    Chunk #{chunk.chunk_index}
                                  </span>
                                  <span className="text-xs text-gray-400">
                                    {chunk.token_count} tokens
                                    {chunk.page_number != null &&
                                      ` · pág. ${chunk.page_number}`}
                                  </span>
                                </div>
                                <pre className="text-xs text-gray-700 leading-relaxed whitespace-pre-wrap font-sans">
                                  {chunk.content}
                                </pre>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Rejection reason */}
                    {s.status === "rejected" && s.review_reason && (
                      <div className="flex items-start gap-1.5 mt-2 text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">
                        <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                        <span>{s.review_reason}</span>
                      </div>
                    )}
                  </div>

                  {/* Actions */}
                  {s.status === "pending" && (
                    <div className="flex items-center gap-1.5 shrink-0">
                      {loading_action === "approve" ? (
                        <span className="w-8 h-8 flex items-center justify-center">
                          <Loader2 className="w-4 h-4 animate-spin text-violet-600" />
                        </span>
                      ) : (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleApprove(s.id);
                          }}
                          className="w-8 h-8 flex items-center justify-center rounded-lg bg-green-50 text-green-600 hover:bg-green-100 transition-colors"
                          title="Aprobar"
                        >
                          <CheckCircle2 className="w-4 h-4" />
                        </button>
                      )}
                      {loading_action === "reject" ? (
                        <span className="w-8 h-8 flex items-center justify-center">
                          <Loader2 className="w-4 h-4 animate-spin text-red-600" />
                        </span>
                      ) : (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            openRejectModal(s.id);
                          }}
                          className="w-8 h-8 flex items-center justify-center rounded-lg bg-red-50 text-red-600 hover:bg-red-100 transition-colors"
                          title="Rechazar"
                        >
                          <XCircle className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  )}
                  {s.status !== "pending" && (
                    <div className="shrink-0">
                      {s.status === "approved" ? (
                        <span className="flex items-center gap-1 text-xs text-green-600">
                          <CheckCircle2 className="w-3.5 h-3.5" />
                          Aprobada
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-xs text-red-600">
                          <XCircle className="w-3.5 h-3.5" />
                          Rechazada
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Suggestion detail modal ───────────────────────────────────── */}
      {selectedSuggestion && (
        <SuggestionModal
          suggestion={selectedSuggestion}
          onClose={() => setSelectedSuggestion(null)}
        />
      )}

      {/* ── Reject modal ─────────────────────────────────────────────── */}
      {rejectModal.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div
            className="fixed inset-0 bg-black/40"
            onClick={() => setRejectModal({ id: "", open: false })}
          />
          <div className="relative bg-white rounded-2xl shadow-xl max-w-md w-full p-6 space-y-4 z-10">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900">
                Rechazar sugerencia
              </h3>
              <button
                onClick={() => setRejectModal({ id: "", open: false })}
                className="p-1 rounded-md text-gray-400 hover:text-gray-600"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <p className="text-sm text-gray-600">
              Indica el motivo del rechazo:
            </p>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              rows={3}
              autoFocus
              placeholder="Ej: Esta sugerencia no es relevante para el contenido del curso..."
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-red-400 focus:border-transparent resize-none"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setRejectModal({ id: "", open: false })}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={handleReject}
                disabled={!rejectReason.trim() || rejecting}
                className="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors flex items-center gap-2"
              >
                {rejecting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {rejecting ? "Rechazando..." : "Rechazar"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
