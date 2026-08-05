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
  ArrowRight,
} from "lucide-react";
import { getDashboard } from "../api/account";
import type { DashboardData } from "../api/account";
import DocBadge from "../components/DocBadge";

function fmtDate(d: string | null) {
  if (!d) return "—";
  return new Intl.DateTimeFormat("es", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(d));
}

/** Métrica destacada. Cifras en la sans con figuras proporcionales: las
 *  tabulares se reservan para columnas que deben alinearse verticalmente. */
function StatTile({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof FileText;
  label: string;
  value: string | number;
  tone: string;
}) {
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2">
        <span
          className={`flex h-7 w-7 items-center justify-center rounded-lg ${tone}`}
        >
          <Icon className="h-4 w-4" />
        </span>
        <span className="text-xs font-medium text-ink-2">{label}</span>
      </div>
      <p className="mt-3 text-3xl leading-none font-semibold tracking-tight text-ink">
        {value}
      </p>
    </div>
  );
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
      <div className="flex h-64 items-center justify-center gap-2 text-ink-3">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span className="text-sm">Cargando panel...</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="note note-danger" role="alert">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
        {error || "Sin datos"}
      </div>
    );
  }

  const m = data.metrics;

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      {/* KPIs — visibles sin scroll (criterio UX de HU-20) */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          icon={FileText}
          label="Documentos"
          value={m.total_documents}
          tone="bg-info-soft text-info-fg"
        />
        <StatTile
          icon={Activity}
          label="Sugerencias"
          value={m.total_suggestions}
          tone="bg-brand-soft text-brand-soft-fg"
        />
        <StatTile
          icon={Clock}
          label="Pendientes"
          value={m.pending_suggestions}
          tone="bg-warning-soft text-warning-fg"
        />
        <StatTile
          icon={TrendingUp}
          label="Tasa de aprobación"
          value={`${Math.round(m.approval_rate * 100)}%`}
          tone="bg-success-soft text-success-fg"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Pendientes de revisión con acceso directo */}
        <section className="card p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="section-title">Pendientes de revisión</h2>
            {m.pending_suggestions > 0 && (
              <button
                onClick={() => navigate("/review")}
                className="flex items-center gap-1 text-xs font-semibold text-brand hover:text-brand-hover"
              >
                Revisar todas
                <ArrowRight className="h-3 w-3" />
              </button>
            )}
          </div>

          {data.pending_documents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-9 text-center">
              <span className="mb-2.5 flex h-10 w-10 items-center justify-center rounded-full bg-success-soft">
                <CheckCircle2 className="h-5 w-5 text-success-fg" />
              </span>
              <p className="text-sm font-medium text-ink">Todo al día</p>
              <p className="mt-0.5 text-xs text-ink-3">
                No hay documentos esperando revisión
              </p>
            </div>
          ) : (
            <ul className="space-y-1.5">
              {data.pending_documents.map((d) => (
                <li key={d.id}>
                  <button
                    onClick={() => navigate(`/review?document_id=${d.id}`)}
                    className="flex w-full items-center justify-between gap-3 rounded-field border border-line px-3 py-2.5 text-left transition-colors hover:border-brand/40 hover:bg-surface-2"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <FileText className="h-4 w-4 shrink-0 text-ink-3" />
                      <span className="truncate text-sm text-ink">
                        {d.filename}
                      </span>
                    </span>
                    {d.pending_suggestions > 0 && (
                      <span className="chip chip-warning shrink-0">
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
        <section className="card p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="section-title">Análisis recientes</h2>
            <button
              onClick={() => navigate("/docs")}
              className="flex items-center gap-1.5 text-xs font-semibold text-brand hover:text-brand-hover"
            >
              <Upload className="h-3.5 w-3.5" />
              Subir documento
            </button>
          </div>

          {data.recent_documents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-9 text-center">
              <span className="mb-2.5 flex h-10 w-10 items-center justify-center rounded-full bg-surface-2">
                <FileText className="h-5 w-5 text-ink-3" />
              </span>
              <p className="text-sm font-medium text-ink">Aún no hay documentos</p>
              <button
                onClick={() => navigate("/docs")}
                className="btn btn-primary btn-sm mt-3"
              >
                Subir el primero
              </button>
            </div>
          ) : (
            <ul className="space-y-1.5">
              {data.recent_documents.map((d) => (
                <li key={d.id}>
                  <button
                    onClick={() => navigate(`/docs/${d.id}`)}
                    className="flex w-full items-center justify-between gap-3 rounded-field border border-line px-3 py-2.5 text-left transition-colors hover:border-brand/40 hover:bg-surface-2"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm text-ink">
                        {d.filename}
                      </span>
                      <span className="mt-0.5 block text-xs text-ink-3">
                        {fmtDate(d.uploaded_at)} · {d.suggestions_count} sugerencia
                        {d.suggestions_count !== 1 ? "s" : ""}
                      </span>
                    </span>
                    <span className="shrink-0">
                      <DocBadge status={d.status} />
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {/* Última ejecución del agente */}
      {data.last_run && (
        <section className="card p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-soft">
                <Activity className="h-4 w-4 text-brand-soft-fg" />
              </span>
              <span className="text-sm text-ink-2">
                Última ejecución del agente:{" "}
                <span className="font-semibold text-ink">
                  {fmtDate(data.last_run.started_at)}
                </span>
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-xs text-ink-3">
              {data.last_run.duration_seconds != null && (
                <span className="tnum">
                  {data.last_run.duration_seconds.toFixed(1)} s
                </span>
              )}
              <span>
                {data.last_run.suggestions_generated} sugerencias generadas
              </span>
              <button
                onClick={() => navigate("/agent-runs")}
                className="flex items-center gap-1 font-semibold text-brand hover:text-brand-hover"
              >
                Ver historial
                <ArrowRight className="h-3 w-3" />
              </button>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
