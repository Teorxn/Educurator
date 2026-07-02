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
    color: "bg-amber-100 text-amber-800 border-amber-200",
  },
  conflict: {
    label: "Conflicto",
    color: "bg-red-100 text-red-800 border-red-200",
  },
  faq: { label: "FAQ", color: "bg-blue-100 text-blue-800 border-blue-200" },
  update: {
    label: "Actualización",
    color: "bg-purple-100 text-purple-800 border-purple-200",
  },
  inconsistency: {
    label: "Inconsistencia",
    color: "bg-orange-100 text-orange-800 border-orange-200",
  },
};

const SEVERITY_BADGE: Record<
  SeverityLevel,
  { label: string; color: string; icon: typeof AlertTriangle }
> = {
  high: {
    label: "Alta",
    color: "bg-red-100 text-red-700 border-red-200",
    icon: AlertCircle,
  },
  medium: {
    label: "Media",
    color: "bg-yellow-100 text-yellow-700 border-yellow-200",
    icon: AlertTriangle,
  },
  low: {
    label: "Baja",
    color: "bg-gray-100 text-gray-600 border-gray-200",
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
      <div className="fixed inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto z-10">
        {/* Header */}
        <div className="sticky top-0 bg-white border-b border-gray-100 px-6 py-4 flex items-center justify-between rounded-t-2xl z-20">
          <div className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-violet-600" />
            <h2 className="text-lg font-semibold text-gray-900">
              Razonamiento completo
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
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
              <span className="text-xs font-medium text-gray-500 bg-gray-50 px-2 py-0.5 rounded-full border border-gray-200">
                {incTypeLabel}
              </span>
            )}
            <span className="text-xs text-gray-400">
              {fmtDate(s.created_at)}
            </span>
          </div>

          {/* Description */}
          <div>
            <h3 className="text-sm font-medium text-gray-500 mb-1">
              Descripción
            </h3>
            <p className="text-sm text-gray-800 leading-relaxed">
              {s.description}
            </p>
          </div>

          {/* Split View para inconsistencias */}
          {incData && (incData.extractA || incData.extractB) && (
            <div>
              <h3 className="text-sm font-medium text-gray-700 mb-2">
                Fragmentos enfrentados
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {incData.extractA && (
                  <div className="bg-red-50 border border-red-200 rounded-xl p-4">
                    <div className="flex items-center gap-1 mb-2">
                      <AlertCircle className="w-4 h-4 text-red-500" />
                      <span className="text-xs font-semibold text-red-700">
                        Fragmento A
                      </span>
                    </div>
                    <pre className="text-xs text-red-900 leading-relaxed whitespace-pre-wrap font-sans">
                      {incData.extractA}
                    </pre>
                  </div>
                )}
                {incData.extractB && (
                  <div className="bg-orange-50 border border-orange-200 rounded-xl p-4">
                    <div className="flex items-center gap-1 mb-2">
                      <AlertTriangle className="w-4 h-4 text-orange-500" />
                      <span className="text-xs font-semibold text-orange-700">
                        Fragmento B
                      </span>
                    </div>
                    <pre className="text-xs text-orange-900 leading-relaxed whitespace-pre-wrap font-sans">
                      {incData.extractB}
                    </pre>
                  </div>
                )}
              </div>
              {incData.suggestion && (
                <div className="mt-3 bg-green-50 border border-green-200 rounded-xl p-4">
                  <span className="text-xs font-semibold text-green-700">
                    Acción sugerida:
                  </span>
                  <p className="text-xs text-green-800 mt-1">
                    {incData.suggestion}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Confidence & Similarity */}
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-violet-50 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-1">
                <Target className="w-4 h-4 text-violet-600" />
                <span className="text-xs font-medium text-gray-500">
                  Confianza
                </span>
              </div>
              <p className="text-2xl font-bold text-violet-700">
                {fmtConfidence(s.confidence_score ?? 0)}
              </p>
            </div>
            {incData && severityStyle && (
              <div className="bg-gray-50 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-1">
                  <SeverityIcon className="w-4 h-4 text-gray-600" />
                  <span className="text-xs font-medium text-gray-500">
                    Severidad
                  </span>
                </div>
                <p className="text-2xl font-bold text-gray-700">
                  {severityStyle.label}
                </p>
              </div>
            )}
            {!incData && (
              <div className="bg-blue-50 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-1">
                  <Brain className="w-4 h-4 text-blue-600" />
                  <span className="text-xs font-medium text-gray-500">
                    Similitud
                  </span>
                </div>
                <p className="text-2xl font-bold text-blue-700">
                  {fmtConfidence(s.confidence_score ?? 0)}
                </p>
              </div>
            )}
          </div>

          {/* Agent Reasoning */}
          {s.reasoning && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <Brain className="w-4 h-4 text-violet-600" />
                <h3 className="text-sm font-medium text-gray-700">
                  Razonamiento del agente
                </h3>
              </div>
              <div className="bg-gray-50 border border-gray-200 rounded-xl p-4">
                <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
                  {s.reasoning}
                </p>
              </div>
            </div>
          )}

          {/* Source Chunks */}
          {s.source_chunks && s.source_chunks.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <ScrollText className="w-4 h-4 text-violet-600" />
                <h3 className="text-sm font-medium text-gray-700">
                  Chunks fuente ({s.source_chunks.length})
                </h3>
              </div>
              <div className="space-y-2">
                {s.source_chunks.map((chunk) => (
                  <div
                    key={chunk.chunk_id}
                    className="bg-gray-50 border border-gray-200 rounded-xl p-4"
                  >
                    <div className="flex items-center justify-between mb-2">
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
            </div>
          )}

          {/* Source document info */}
          {s.source_type && (
            <div className="flex items-center gap-2 text-xs text-gray-500 bg-gray-50 rounded-xl px-4 py-3">
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
