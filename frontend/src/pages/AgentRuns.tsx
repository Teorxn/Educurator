import { useEffect, useRef, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Clock,
  ExternalLink,
  GitBranch,
  Loader2,
  Play,
  XCircle,
} from "lucide-react";
import AgentGraphModal from "../components/AgentGraph";
import Skeleton, { SkeletonTable, LoadingLabel } from "../components/Skeleton";
import { getCurationRuns, triggerCuration } from "../api/analysis";
import type { AgentRun } from "../api/analysis";
import { keepIfSame } from "../lib/sameData";

const STATUS_BADGE: Record<
  string,
  { label: string; tone: string; icon: typeof CheckCircle2 }
> = {
  running: { label: "En ejecución", tone: "chip-info", icon: Loader2 },
  completed: { label: "Completada", tone: "chip-success", icon: CheckCircle2 },
  failed: { label: "Fallida", tone: "chip-danger", icon: XCircle },
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
  const [showGraph, setShowGraph] = useState(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchRuns = async (isFirstLoad = false) => {
    try {
      const { data } = await getCurationRuns();
      // Sin novedades no se toca el estado: el sondeo cada 5 s no debe
      // repintar la tabla.
      setRuns((prev) => keepIfSame(prev, data.runs));

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

  return (
    <div className="space-y-4">
      {/* Toolbar — se dibuja desde el primer momento, también mientras carga:
          así la página no aparece de golpe cuando llega la respuesta. */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        {loading ? (
          <>
            <Skeleton className="h-5 w-48" />
            <LoadingLabel>Cargando ejecuciones</LoadingLabel>
          </>
        ) : (
          <p className="text-sm text-ink-2">
            {runs.length} ejecuci{runs.length !== 1 ? "ones" : "ón"} registrada
            {runs.length !== 1 ? "s" : ""}
          </p>
        )}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowGraph(true)}
            data-tour="agent-graph"
            className="btn btn-secondary"
          >
            <GitBranch className="w-4 h-4" />
            Ver grafo del agente
          </button>
          <button
            onClick={handleTrigger}
            disabled={triggering}
            className="btn btn-primary"
          >
            {triggering ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            Ejecutar análisis
          </button>
        </div>
      </div>

      <AgentGraphModal open={showGraph} onClose={() => setShowGraph(false)} />

      {notice && <div className="note note-brand">{notice}</div>}

      {loading ? (
        <div className="card overflow-hidden">
          <SkeletonTable
            rows={4}
            cols={["w-32", "w-24", "w-16", "w-10", "w-10", "w-28"]}
          />
        </div>
      ) : runs.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-center">
          <div className="w-14 h-14 bg-surface-2 rounded-2xl flex items-center justify-center mb-4">
            <Activity className="w-7 h-7 text-ink-3" />
          </div>
          <p className="text-ink-2 font-medium">Sin ejecuciones aún</p>
          <p className="text-sm text-ink-3 mt-1">
            Sube un documento o dispara el análisis manualmente
          </p>
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-2 border-b border-line">
              <tr>
                <th className="table-head">Fecha</th>
                <th className="table-head">Estado</th>
                <th className="table-head">Duración</th>
                <th className="table-head">Docs</th>
                <th className="table-head">Sugerencias</th>
                <th className="table-head">Resumen</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {runs.map((run) => {
                const badge = STATUS_BADGE[run.status] ?? STATUS_BADGE.running;
                const Icon = badge.icon;
                return (
                  <tr
                    key={run.thread_id}
                    className="hover:bg-surface-2 transition-colors"
                  >
                    <td className="table-cell text-xs whitespace-nowrap">
                      {fmtDate(run.started_at)}
                    </td>
                    <td className="table-cell">
                      <span
                        className={`chip ${badge.tone}`}
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
                    <td className="table-cell whitespace-nowrap">
                      <span className="inline-flex items-center gap-1">
                        <Clock className="w-3 h-3 text-ink-3" />
                        <span className="tnum">
                          {fmtDuration(run.duration_seconds)}
                        </span>
                      </span>
                    </td>
                    <td className="table-cell tnum">
                      {run.documents_processed}
                    </td>
                    <td className="table-cell tnum">
                      {run.suggestions_generated}
                    </td>
                    <td className="table-cell text-xs">
                      <span className="inline-flex items-center gap-2">
                        {fmtSummary(run)}
                        {run.trace_url && (
                          <a
                            href={run.trace_url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-brand hover:text-brand-hover"
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
