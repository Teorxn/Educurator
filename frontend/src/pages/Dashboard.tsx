import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Activity,
  CheckCircle2,
  Clock,
  FileText,
  Loader2,
  Upload,
  AlertCircle,
  TrendingUp,
} from "lucide-react";
import { getDashboard } from "../api/account";
import type { DashboardData } from "../api/account";

const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  queued: { label: "En cola", color: "bg-gray-100 text-gray-700" },
  processing: { label: "Procesando", color: "bg-blue-50 text-blue-700" },
  analyzed: { label: "Analizado", color: "bg-violet-50 text-violet-700" },
  error: { label: "Error", color: "bg-red-50 text-red-700" },
  needs_review: { label: "Por revisar", color: "bg-yellow-50 text-yellow-700" },
  approved: { label: "Aprobado", color: "bg-green-50 text-green-700" },
  rejected: { label: "Rechazado", color: "bg-red-50 text-red-700" },
  archived: { label: "Archivado", color: "bg-gray-100 text-gray-500" },
};

function fmtDate(d: string | null) {
  if (!d) return "—";
  return new Intl.DateTimeFormat("es", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(d));
}

/** HU-20 — Panel de inicio: resumen del estado de la base de conocimiento. */
export default function Dashboard() {
  const navigate = useNavigate();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = async (first = false) => {
    try {
      const { data } = await getDashboard();
      setData(data);
      setError("");
    } catch {
      if (first) setError("No se pudo cargar el panel.");
    } finally {
      if (first) setLoading(false);
    }
  };

  useEffect(() => {
    load(true);
    // Datos frescos sin recargar la página (RNF de HU-20)
    pollRef.current = setInterval(() => load(false), 15000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400 gap-2">
        <Loader2 className="w-5 h-5 animate-spin" />
        <span className="text-sm">Cargando panel...</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3">
        <AlertCircle className="w-4 h-4 shrink-0" />
        {error || "Sin datos"}
      </div>
    );
  }

  const m = data.metrics;
  const kpis = [
    {
      label: "Documentos",
      value: m.total_documents,
      icon: FileText,
      color: "text-blue-600 bg-blue-50",
    },
    {
      label: "Sugerencias",
      value: m.total_suggestions,
      icon: Activity,
      color: "text-violet-600 bg-violet-50",
    },
    {
      label: "Pendientes",
      value: m.pending_suggestions,
      icon: Clock,
      color: "text-yellow-600 bg-yellow-50",
    },
    {
      label: "Tasa de aprobación",
      value: `${Math.round(m.approval_rate * 100)}%`,
      icon: TrendingUp,
      color: "text-green-600 bg-green-50",
    },
  ];

  return (
    <div className="space-y-5">
      {/* KPIs — visibles sin scroll (criterio UX de HU-20) */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {kpis.map(({ label, value, icon: Icon, color }) => (
          <div
            key={label}
            className="bg-white rounded-xl border border-gray-200 p-4"
          >
            <div className="flex items-center gap-2 mb-2">
              <span className={`p-1.5 rounded-lg ${color}`}>
                <Icon className="w-4 h-4" />
              </span>
              <span className="text-xs text-gray-500">{label}</span>
            </div>
            <p className="text-2xl font-semibold text-gray-900">{value}</p>
          </div>
        ))}
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        {/* Pendientes de revisión con acceso directo */}
        <section className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-800">
              Pendientes de revisión
            </h2>
            {m.pending_suggestions > 0 && (
              <button
                onClick={() => navigate("/review")}
                className="text-xs font-medium text-violet-600 hover:text-violet-700"
              >
                Revisar todas →
              </button>
            )}
          </div>

          {data.pending_documents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <CheckCircle2 className="w-8 h-8 text-green-500 mb-2" />
              <p className="text-sm text-gray-600">Todo al día</p>
              <p className="text-xs text-gray-400 mt-0.5">
                No hay documentos esperando revisión
              </p>
            </div>
          ) : (
            <ul className="space-y-2">
              {data.pending_documents.map((d) => (
                <li key={d.id}>
                  <button
                    onClick={() => navigate(`/review?document_id=${d.id}`)}
                    className="w-full flex items-center justify-between gap-3 p-2.5 rounded-lg border border-gray-100 hover:border-violet-200 hover:bg-violet-50/40 transition-colors text-left"
                  >
                    <span className="flex items-center gap-2 min-w-0">
                      <FileText className="w-4 h-4 text-gray-400 shrink-0" />
                      <span className="text-sm text-gray-700 truncate">
                        {d.filename}
                      </span>
                    </span>
                    {d.pending_suggestions > 0 && (
                      <span className="text-xs font-medium text-yellow-700 bg-yellow-50 border border-yellow-200 px-2 py-0.5 rounded-full shrink-0">
                        {d.pending_suggestions} pendiente
                        {d.pending_suggestions !== 1 ? "s" : ""}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Análisis recientes */}
        <section className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-800">
              Análisis recientes
            </h2>
            <button
              onClick={() => navigate("/upload")}
              className="flex items-center gap-1.5 text-xs font-medium text-violet-600 hover:text-violet-700"
            >
              <Upload className="w-3.5 h-3.5" />
              Subir documento
            </button>
          </div>

          {data.recent_documents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <FileText className="w-8 h-8 text-gray-300 mb-2" />
              <p className="text-sm text-gray-600">Aún no hay documentos</p>
              <button
                onClick={() => navigate("/upload")}
                className="mt-3 text-xs font-medium bg-violet-600 hover:bg-violet-700 text-white px-3 py-1.5 rounded-lg"
              >
                Subir el primero
              </button>
            </div>
          ) : (
            <ul className="space-y-2">
              {data.recent_documents.map((d) => {
                const st = STATUS_LABEL[d.status] ?? STATUS_LABEL.needs_review;
                return (
                  <li key={d.id}>
                    <button
                      onClick={() => navigate(`/docs/${d.id}`)}
                      className="w-full flex items-center justify-between gap-3 p-2.5 rounded-lg border border-gray-100 hover:border-violet-200 hover:bg-violet-50/40 transition-colors text-left"
                    >
                      <span className="min-w-0">
                        <span className="block text-sm text-gray-700 truncate">
                          {d.filename}
                        </span>
                        <span className="block text-xs text-gray-400 mt-0.5">
                          {fmtDate(d.uploaded_at)} · {d.suggestions_count}{" "}
                          sugerencia{d.suggestions_count !== 1 ? "s" : ""}
                        </span>
                      </span>
                      <span
                        className={`text-xs font-medium px-2 py-0.5 rounded-full shrink-0 ${st.color}`}
                      >
                        {st.label}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>

      {/* Última ejecución del agente */}
      {data.last_run && (
        <section className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-violet-500" />
              <span className="text-sm text-gray-700">
                Última ejecución del agente:{" "}
                <span className="font-medium">
                  {fmtDate(data.last_run.started_at)}
                </span>
              </span>
            </div>
            <div className="flex items-center gap-3 text-xs text-gray-500">
              {data.last_run.duration_seconds != null && (
                <span>{data.last_run.duration_seconds.toFixed(1)} s</span>
              )}
              <span>
                {data.last_run.suggestions_generated} sugerencias generadas
              </span>
              <button
                onClick={() => navigate("/agent-runs")}
                className="font-medium text-violet-600 hover:text-violet-700"
              >
                Ver historial →
              </button>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
