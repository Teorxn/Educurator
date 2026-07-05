import { useEffect, useRef, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Clock,
  ExternalLink,
  Loader2,
  Play,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { getCurationRuns, triggerCuration } from "../api/analysis";
import type { AgentRun } from "../api/analysis";

const STATUS_BADGE: Record<
  string,
  { label: string; color: string; icon: typeof CheckCircle2 }
> = {
  running: {
    label: "En ejecución",
    color: "bg-blue-50 text-blue-700 border-blue-200",
    icon: Loader2,
  },
  completed: {
    label: "Completada",
    color: "bg-green-50 text-green-700 border-green-200",
    icon: CheckCircle2,
  },
  failed: {
    label: "Fallida",
    color: "bg-red-50 text-red-700 border-red-200",
    icon: XCircle,
  },
};

function fmtDate(d: string | null) {
  if (!d) return "—";
  return new Intl.DateTimeFormat("es", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(d));
}

function fmtDuration(s: number | null) {
  if (s == null) return "—";
  if (s < 60) return `${s.toFixed(1)} s`;
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

function fmtSummary(run: AgentRun): string {
  const byType = run.summary?.suggestions_by_type ?? {};
  const parts = Object.entries(byType).map(([t, n]) => `${n} ${t}`);
  return parts.length > 0 ? parts.join(" · ") : "—";
}

export default function AgentRuns() {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [notice, setNotice] = useState("");
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchRuns = async (isFirstLoad = false) => {
    try {
      const { data } = await getCurationRuns();
      setRuns(data.runs);

      // Dejar de refrescar cuando no hay corridas en ejecución
      const hasRunning = data.runs.some((r) => r.status === "running");
      if (!hasRunning && pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    } catch {
      // silent on background polls
    } finally {
      if (isFirstLoad) setLoading(false);
    }
  };

  const startPolling = () => {
    if (!pollingRef.current) {
      pollingRef.current = setInterval(() => fetchRuns(false), 5000);
    }
  };

  useEffect(() => {
    fetchRuns(true);
    startPolling();
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleTrigger = async () => {
    setTriggering(true);
    setNotice("");
    try {
      const { data } = await triggerCuration();
      setNotice(`Análisis iniciado (${data.thread_id})`);
      await fetchRuns(false);
      startPolling();
    } catch {
      setNotice("No se pudo iniciar el análisis. Verifica tu rol e intenta de nuevo.");
    } finally {
      setTriggering(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400 gap-2">
        <RefreshCw className="w-5 h-5 animate-spin" />
        <span className="text-sm">Cargando ejecuciones...</span>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <p className="text-sm text-gray-500">
          {runs.length} ejecuci{runs.length !== 1 ? "ones" : "ón"} registrada
          {runs.length !== 1 ? "s" : ""}
        </p>
        <button
          onClick={handleTrigger}
          disabled={triggering}
          className="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 disabled:bg-violet-300 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          {triggering ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Play className="w-4 h-4" />
          )}
          Ejecutar análisis
        </button>
      </div>

      {notice && (
        <div className="text-sm text-violet-700 bg-violet-50 border border-violet-200 rounded-xl px-4 py-3">
          {notice}
        </div>
      )}

      {runs.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-center">
          <div className="w-14 h-14 bg-gray-100 rounded-2xl flex items-center justify-center mb-4">
            <Activity className="w-7 h-7 text-gray-400" />
          </div>
          <p className="text-gray-600 font-medium">Sin ejecuciones aún</p>
          <p className="text-sm text-gray-400 mt-1">
            Sube un documento o dispara el análisis manualmente
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Fecha
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Estado
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Duración
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Docs
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Sugerencias
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Resumen
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {runs.map((run) => {
                const badge = STATUS_BADGE[run.status] ?? STATUS_BADGE.running;
                const Icon = badge.icon;
                return (
                  <tr
                    key={run.thread_id}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-4 py-3 text-gray-600 text-xs whitespace-nowrap">
                      {fmtDate(run.started_at)}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full border ${badge.color}`}
                        title={run.error ?? undefined}
                      >
                        <Icon
                          className={`w-3 h-3 ${
                            run.status === "running" ? "animate-spin" : ""
                          }`}
                        />
                        {badge.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                      <span className="inline-flex items-center gap-1">
                        <Clock className="w-3 h-3 text-gray-400" />
                        {fmtDuration(run.duration_seconds)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-600">
                      {run.documents_processed}
                    </td>
                    <td className="px-4 py-3 text-gray-600">
                      {run.suggestions_generated}
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      <span className="inline-flex items-center gap-2">
                        {fmtSummary(run)}
                        {run.trace_url && (
                          <a
                            href={run.trace_url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-violet-600 hover:text-violet-700"
                            title="Ver traza en Langfuse"
                          >
                            <ExternalLink className="w-3 h-3" />
                          </a>
                        )}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
