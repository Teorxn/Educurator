import {
  X,
  Brain,
  ScrollText,
  FileText,
  Target,
  AlertTriangle,
  AlertCircle,
  Info,
} from "lucide-react";
import type { Suggestion } from "../api/docs";
import type { SeverityLevel } from "../api/suggestions";

const TYPE_LABEL: Record<string, { label: string; color: string }> = {
  redundancy: {
    label: "Redundancia",
    color: "bg-warning-soft text-warning-fg border-transparent",
  },
  conflict: {
    label: "Conflicto",
    color: "bg-danger-soft text-danger-fg border-transparent",
  },
  faq: { label: "FAQ", color: "bg-info-soft text-info-fg border-transparent" },
  update: {
    label: "Actualización",
    color: "bg-brand-soft text-brand-soft-fg border-transparent",
  },
  inconsistency: {
    label: "Inconsistencia",
    color: "bg-warning-soft text-warning-fg border-transparent",
  },
};

const SEVERITY_BADGE: Record<
  SeverityLevel,
  { label: string; color: string; icon: typeof AlertTriangle }
> = {
  high: {
    label: "Alta",
    color: "bg-danger-soft text-danger-fg border-transparent",
    icon: AlertCircle,
  },
  medium: {
    label: "Media",
    color: "bg-warning-soft text-warning-fg border-transparent",
    icon: AlertTriangle,
  },
  low: {
    label: "Baja",
    color: "bg-surface-2 text-ink-2 border-line",
    icon: Info,
  },
};

const INC_TYPE_LABEL: Record<string, string> = {
  self_contradiction: "Auto-contradicción",
  terminology: "Terminología inconsistente",
  numerical: "Valor numérico contradictorio",
  structural: "Inconsistencia estructural",
};

function fmtDate(d: string) {
  return new Intl.DateTimeFormat("es", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(d));
}

function fmtConfidence(score: number) {
  return `${(score * 100).toFixed(0)}%`;
}

function extractInconsistencyData(description: string): {
  extractA: string;
  extractB: string;
  incType: string;
  severity: SeverityLevel;
  suggestion: string;
} | null {
  // Intentar extraer datos estructurados de la descripción/reasoning
  // Formato: [Tipo] descripción\n\nFragmento A: ...\nFragmento B: ...\n\nSugerencia: ...
  const typeMatch = description.match(/^\[([^\]]+)\]\s*(.+)$/);
  const extractAMatch = description.match(/Fragmento A:\s*(.+?)(?:\n|$)/);
  const extractBMatch = description.match(/Fragmento B:\s*(.+?)(?:\n|$)/);
  const suggestionMatch = description.match(/Sugerencia:\s*(.+?)$/m);

  // Detectar severidad por palabras clave
  let severity: SeverityLevel = "medium";
  if (
    description.includes("Auto-contradicción") ||
    description.includes("contradictorio")
  ) {
    severity = "high";
  } else if (description.includes("estructural")) {
    severity = "low";
  }

  const incType = typeMatch?.[1] ?? "conflict";

  return {
    extractA: extractAMatch?.[1]?.trim() ?? "",
    extractB: extractBMatch?.[1]?.trim() ?? "",
    incType,
    severity,
    suggestion: suggestionMatch?.[1]?.trim() ?? "",
  };
}

interface Props {
  suggestion: Suggestion;
  onClose: () => void;
}

export default function SuggestionModal({ suggestion: s, onClose }: Props) {
  const typeStyle = TYPE_LABEL[s.type] ?? TYPE_LABEL.redundancy;
  const incData = extractInconsistencyData(s.description);
  const severityStyle = incData ? SEVERITY_BADGE[incData.severity] : null;
  const SeverityIcon = severityStyle?.icon ?? AlertTriangle;
  const incTypeLabel = incData
    ? (INC_TYPE_LABEL[incData.incType] ?? incData.incType)
    : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="fixed inset-0 bg-black/50 backdrop-blur-[2px]" onClick={onClose} />
      <div className="relative bg-surface border border-line rounded-2xl shadow-[var(--shadow-overlay)] max-w-2xl w-full max-h-[90vh] overflow-y-auto z-10">
        {/* Header */}
        <div className="sticky top-0 bg-surface border-b border-line px-6 py-4 flex items-center justify-between rounded-t-2xl z-20">
          <div className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-brand" />
            <h2 className="text-lg font-semibold text-ink">
              Razonamiento completo
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-ink-3 hover:text-ink-2 hover:bg-surface-2 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-6 py-4 space-y-5">
          {/* Type & Status badges + Severity badge */}
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${typeStyle.color}`}
            >
              {typeStyle.label}
            </span>
            {incData && severityStyle && (
              <span
                className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full border ${severityStyle.color}`}
              >
                <SeverityIcon className="w-3 h-3" />
                {severityStyle.label}
              </span>
            )}
            {incTypeLabel && (
              <span className="text-xs font-medium text-ink-2 bg-surface-2 px-2 py-0.5 rounded-full border border-line">
                {incTypeLabel}
              </span>
            )}
            <span className="text-xs text-ink-3">
              {fmtDate(s.created_at)}
            </span>
          </div>

          {/* Description */}
          <div>
            <h3 className="text-sm font-medium text-ink-2 mb-1">
              Descripción
            </h3>
            <p className="text-sm text-ink leading-relaxed">
              {s.description}
            </p>
          </div>

          {/* Split View para inconsistencias */}
          {incData && (incData.extractA || incData.extractB) && (
            <div>
              <h3 className="text-sm font-medium text-ink mb-2">
                Fragmentos enfrentados
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {incData.extractA && (
                  <div className="bg-danger-soft border border-transparent rounded-xl p-4">
                    <div className="flex items-center gap-1 mb-2">
                      <AlertCircle className="w-4 h-4 text-danger-fg" />
                      <span className="text-xs font-semibold text-danger-fg">
                        Fragmento A
                      </span>
                    </div>
                    <pre className="text-xs text-danger-fg leading-relaxed whitespace-pre-wrap font-sans">
                      {incData.extractA}
                    </pre>
                  </div>
                )}
                {incData.extractB && (
                  <div className="bg-warning-soft border border-transparent rounded-xl p-4">
                    <div className="flex items-center gap-1 mb-2">
                      <AlertTriangle className="w-4 h-4 text-warning-fg" />
                      <span className="text-xs font-semibold text-warning-fg">
                        Fragmento B
                      </span>
                    </div>
                    <pre className="text-xs text-warning-fg leading-relaxed whitespace-pre-wrap font-sans">
                      {incData.extractB}
                    </pre>
                  </div>
                )}
              </div>
              {incData.suggestion && (
                <div className="mt-3 bg-success-soft border border-transparent rounded-xl p-4">
                  <span className="text-xs font-semibold text-success-fg">
                    Acción sugerida:
                  </span>
                  <p className="text-xs text-success-fg mt-1">
                    {incData.suggestion}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Confidence & Similarity */}
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-brand-soft rounded-xl p-4">
              <div className="flex items-center gap-2 mb-1">
                <Target className="w-4 h-4 text-brand" />
                <span className="text-xs font-medium text-ink-2">
                  Confianza
                </span>
              </div>
              <p className="text-2xl font-bold text-brand">
                {fmtConfidence(s.confidence_score ?? 0)}
              </p>
            </div>
            {incData && severityStyle && (
              <div className="bg-surface-2 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-1">
                  <SeverityIcon className="w-4 h-4 text-ink-2" />
                  <span className="text-xs font-medium text-ink-2">
                    Severidad
                  </span>
                </div>
                <p className="text-2xl font-bold text-ink">
                  {severityStyle.label}
                </p>
              </div>
            )}
            {!incData && (
              <div className="bg-info-soft rounded-xl p-4">
                <div className="flex items-center gap-2 mb-1">
                  <Brain className="w-4 h-4 text-info-fg" />
                  <span className="text-xs font-medium text-ink-2">
                    Similitud
                  </span>
                </div>
                <p className="text-2xl font-bold text-info-fg">
                  {fmtConfidence(s.confidence_score ?? 0)}
                </p>
              </div>
            )}
          </div>

          {/* Agent Reasoning */}
          {s.reasoning && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <Brain className="w-4 h-4 text-brand" />
                <h3 className="text-sm font-medium text-ink">
                  Razonamiento del agente
                </h3>
              </div>
              <div className="bg-surface-2 border border-line rounded-xl p-4">
                <p className="text-sm text-ink leading-relaxed whitespace-pre-wrap">
                  {s.reasoning}
                </p>
              </div>
            </div>
          )}

          {/* Source Chunks */}
          {s.source_chunks && s.source_chunks.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <ScrollText className="w-4 h-4 text-brand" />
                <h3 className="text-sm font-medium text-ink">
                  Chunks fuente ({s.source_chunks.length})
                </h3>
              </div>
              <div className="space-y-2">
                {s.source_chunks.map((chunk) => (
                  <div
                    key={chunk.chunk_id}
                    className="bg-surface-2 border border-line rounded-xl p-4"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-medium text-ink-2">
                        Chunk #{chunk.chunk_index}
                      </span>
                      <span className="text-xs text-ink-3">
                        {chunk.token_count} tokens
                        {chunk.page_number != null &&
                          ` · pág. ${chunk.page_number}`}
                      </span>
                    </div>
                    <pre className="text-xs text-ink leading-relaxed whitespace-pre-wrap font-sans">
                      {chunk.content}
                    </pre>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Source document info */}
          {s.source_type && (
            <div className="flex items-center gap-2 text-xs text-ink-2 bg-surface-2 rounded-xl px-4 py-3">
              <FileText className="w-3.5 h-3.5" />
              <span>
                Fuente:{" "}
                {s.source_type === "reference"
                  ? "Documento de referencia"
                  : "Documento curado"}
                {s.source_doc_id && ` (ID: ${s.source_doc_id.slice(0, 8)}...)`}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
