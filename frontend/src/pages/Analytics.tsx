/**
 * HU-18: Consultar métricas del sistema
 */
import { useEffect, useState } from "react";
import {
  BarChart3,
  Clock,
  FileText,
  CheckCircle2,
  TrendingUp,
  RefreshCw,
} from "lucide-react";
import { getAnalytics, type AnalyticsData } from "../api/suggestions";
import TokenUsagePanel from "../components/TokenUsagePanel";

function StatCard({
  icon: Icon,
  label,
  value,
  color,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string | number;
  color: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 flex items-center gap-4">
      <div
        className={`w-10 h-10 rounded-xl flex items-center justify-center ${color}`}
      >
        <Icon className="w-5 h-5" />
      </div>
      <div>
        <p className="text-2xl font-bold text-gray-900">{value}</p>
        <p className="text-xs text-gray-500 mt-0.5">{label}</p>
      </div>
    </div>
  );
}

function BarRow({
  label,
  value,
  max,
  color,
}: {
  label: string;
  value: number;
  max: number;
  color: string;
}) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="w-24 text-xs text-gray-600 shrink-0 capitalize">
        {label}
      </span>
      <div className="flex-1 bg-gray-100 rounded-full h-2">
        <div
          className={`h-2 rounded-full ${color} transition-all duration-500`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-6 text-xs text-gray-500 text-right">{value}</span>
    </div>
  );
}

const TYPE_COLORS: Record<string, string> = {
  redundancy: "bg-yellow-400",
  conflict: "bg-red-400",
  faq: "bg-blue-400",
  update: "bg-purple-400",
};

const STATUS_COLORS: Record<string, string> = {
  needs_review: "bg-gray-400",
  processing: "bg-yellow-400",
  approved: "bg-green-400",
  rejected: "bg-red-400",
  archived: "bg-blue-400",
};

export default function Analytics() {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoad] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    getAnalytics()
      .then(({ data }) => setData(data))
      .catch(() => setError(true))
      .finally(() => setLoad(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400 gap-2">
        <RefreshCw className="w-5 h-5 animate-spin" />
        <span className="text-sm">Cargando métricas...</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-400">
        <BarChart3 className="w-10 h-10 mb-3 opacity-40" />
        <p className="text-sm">No se pudieron cargar las métricas</p>
        <p className="text-xs mt-1 text-gray-400">
          Verifica que el backend esté corriendo en :8000
        </p>
      </div>
    );
  }

  const maxDocStatus = Math.max(...Object.values(data.by_status), 1);
  const maxSugType = Math.max(...Object.values(data.suggestions_by_type), 1);
  const pending = data.suggestions_by_status["pending"] ?? 0;
  const approved = data.suggestions_by_status["approved"] ?? 0;
  const rejected = data.suggestions_by_status["rejected"] ?? 0;

  return (
    <div className="space-y-6">
      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={FileText}
          label="Documentos totales"
          value={data.total_documents}
          color="bg-blue-50 text-blue-600"
        />
        <StatCard
          icon={BarChart3}
          label="Sugerencias totales"
          value={data.total_suggestions}
          color="bg-violet-50 text-violet-600"
        />
        <StatCard
          icon={CheckCircle2}
          label="Aprobadas"
          value={approved}
          color="bg-green-50 text-green-600"
        />
        <StatCard
          icon={TrendingUp}
          label="Tasa de aprobación"
          value={`${Math.round(data.approval_rate * 100)}%`}
          color="bg-emerald-50 text-emerald-600"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Docs by status */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-800 mb-4">
            Documentos por estado
          </h2>
          <div className="space-y-3">
            {Object.entries(data.by_status).length === 0 ? (
              <p className="text-xs text-gray-400">Sin datos aún</p>
            ) : (
              Object.entries(data.by_status).map(([status, count]) => (
                <BarRow
                  key={status}
                  label={status.replace("_", " ")}
                  value={count}
                  max={maxDocStatus}
                  color={STATUS_COLORS[status] ?? "bg-gray-400"}
                />
              ))
            )}
          </div>
        </div>

        {/* Suggestions by type */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-800 mb-4">
            Sugerencias por tipo
          </h2>
          <div className="space-y-3">
            {Object.entries(data.suggestions_by_type).length === 0 ? (
              <p className="text-xs text-gray-400">Sin sugerencias aún</p>
            ) : (
              Object.entries(data.suggestions_by_type).map(([type, count]) => (
                <BarRow
                  key={type}
                  label={type}
                  value={count}
                  max={maxSugType}
                  color={TYPE_COLORS[type] ?? "bg-gray-400"}
                />
              ))
            )}
          </div>
        </div>

        {/* Suggestions status donut (manual) */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-800 mb-4">
            Estado de sugerencias
          </h2>
          <div className="flex items-center gap-6">
            <div className="relative w-24 h-24 shrink-0">
              <svg viewBox="0 0 36 36" className="-rotate-90 w-full h-full">
                {
                  [
                    { value: pending, color: "#6b7280" },
                    { value: approved, color: "#22c55e" },
                    { value: rejected, color: "#ef4444" },
                  ].reduce<{ offset: number; els: React.JSX.Element[] }>(
                    ({ offset, els }, { value, color }, i) => {
                      const total = data.total_suggestions || 1;
                      const pct = (value / total) * 100;
                      els.push(
                        <circle
                          key={i}
                          cx="18"
                          cy="18"
                          r="15.9"
                          fill="none"
                          stroke={color}
                          strokeWidth="3.5"
                          strokeDasharray={`${pct} ${100 - pct}`}
                          strokeDashoffset={-offset}
                        />,
                      );
                      return { offset: offset + pct, els };
                    },
                    { offset: 0, els: [] },
                  ).els
                }
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-xs font-bold text-gray-700">
                {data.total_suggestions}
              </span>
            </div>
            <div className="space-y-2 text-xs">
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-gray-400 inline-block" />
                <span className="text-gray-600">Pendiente: {pending}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-green-500 inline-block" />
                <span className="text-gray-600">Aprobada: {approved}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-red-500 inline-block" />
                <span className="text-gray-600">Rechazada: {rejected}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Pending actions */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-800 mb-4">
            Acciones pendientes
          </h2>
          <div className="space-y-3">
            <div className="flex items-center gap-3 p-3 bg-yellow-50 rounded-lg border border-yellow-100">
              <Clock className="w-4 h-4 text-yellow-600 shrink-0" />
              <div>
                <p className="text-sm font-medium text-yellow-800">
                  {pending} sugerencia{pending !== 1 ? "s" : ""} por revisar
                </p>
                <p className="text-xs text-yellow-600 mt-0.5">
                  Ve a Revisión para aprobar o rechazar
                </p>
              </div>
            </div>
            {(data.by_status["needs_review"] ?? 0) > 0 && (
              <div className="flex items-center gap-3 p-3 bg-blue-50 rounded-lg border border-blue-100">
                <FileText className="w-4 h-4 text-blue-600 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-blue-800">
                    {data.by_status["needs_review"]} documento
                    {(data.by_status["needs_review"] ?? 0) !== 1 ? "s" : ""} sin
                    analizar
                  </p>
                  <p className="text-xs text-blue-600 mt-0.5">
                    Esperando procesamiento del agente
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
      {/* HU-32 — consumo de tokens y costo estimado */}
      <TokenUsagePanel />

    </div>
  );
}
