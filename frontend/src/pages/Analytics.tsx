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
  XCircle,
} from "lucide-react";
import { getAnalytics, type AnalyticsData } from "../api/suggestions";
import TokenUsagePanel from "../components/TokenUsagePanel";

const STATUS_LABEL: Record<string, string> = {
  queued: "En cola",
  processing: "Procesando",
  analyzed: "Analizado",
  error: "Error",
  needs_review: "Por revisar",
  approved: "Aprobado",
  rejected: "Rechazado",
  archived: "Archivado",
};

const TYPE_LABEL: Record<string, string> = {
  redundancy: "Redundancia",
  conflict: "Conflicto",
  faq: "FAQ",
  update: "Actualización",
  inconsistency: "Inconsistencia",
};

function StatCard({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string | number;
  tone: string;
}) {
  return (
    <div className="card flex items-center gap-4 p-5">
      <div
        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${tone}`}
      >
        <Icon className="h-5 w-5" />
      </div>
      <div className="min-w-0">
        {/* Figuras proporcionales: las tabulares se reservan para columnas */}
        <p className="text-2xl leading-none font-semibold tracking-tight text-ink">
          {value}
        </p>
        <p className="mt-1 text-xs text-ink-2">{label}</p>
      </div>
    </div>
  );
}

/**
 * Fila de barra horizontal. Una sola serie ⇒ un solo color: la etiqueta ya
 * identifica la categoría, así que teñir cada barra de un matiz distinto
 * gastaría el canal de color en información que la fila ya muestra.
 */
function BarRow({
  label,
  value,
  max,
  total,
}: {
  label: string;
  value: number;
  max: number;
  total: number;
}) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  const share = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="w-28 shrink-0 truncate text-xs text-ink-2" title={label}>
        {label}
      </span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-chart-track">
        <div
          className="h-2 rounded-full bg-chart transition-[width] duration-500"
          style={{ width: `${Math.max(pct, value > 0 ? 2 : 0)}%` }}
          role="img"
          aria-label={`${label}: ${value} (${share}%)`}
        />
      </div>
      <span className="tnum w-14 shrink-0 text-right text-xs text-ink-2">
        {value}
        <span className="ml-1 text-ink-3">{share}%</span>
      </span>
    </div>
  );
}

/**
 * Dona de estado de sugerencias. Usa la paleta de estado (fija, no tematizada)
 * y la leyenda muestra la cifra exacta de cada segmento, de modo que ningún
 * valor depende de distinguir el color ni de pasar el cursor por encima.
 */
function StatusDonut({
  segments,
  total,
}: {
  segments: { label: string; value: number; color: string; icon: typeof Clock }[];
  total: number;
}) {
  // Hueco de 1.2 unidades entre segmentos (la circunferencia con r=15.9 mide
  // ~100), en lugar de un borde: separa sin añadir un trazo extra.
  const GAP = 1.2;

  // Los desplazamientos se acumulan con un reduce puro: mutar una variable
  // suelta durante el render es justo lo que el compilador de React marca.
  const arcs = segments.reduce<
    { label: string; value: number; color: string; pct: number; dash: number; offset: number }[]
  >((acc, s) => {
    const pct = total > 0 ? (s.value / total) * 100 : 0;
    const offset = acc.reduce((sum, a) => sum + a.pct, 0);
    acc.push({
      label: s.label,
      value: s.value,
      color: s.color,
      pct,
      dash: Math.max(0, pct - (pct > GAP ? GAP : 0)),
      offset,
    });
    return acc;
  }, []);

  return (
    <div className="flex flex-wrap items-center gap-6">
      <div className="relative h-28 w-28 shrink-0">
        <svg viewBox="0 0 36 36" className="h-full w-full -rotate-90">
          <circle
            cx="18"
            cy="18"
            r="15.9"
            fill="none"
            className="stroke-chart-track"
            strokeWidth="3.5"
          />
          {arcs.map((a) =>
            a.pct > 0 ? (
              <circle
                key={a.label}
                cx="18"
                cy="18"
                r="15.9"
                fill="none"
                stroke={a.color}
                strokeWidth="3.5"
                strokeDasharray={`${a.dash} ${100 - a.dash}`}
                strokeDashoffset={-a.offset}
              >
                <title>{`${a.label}: ${a.value}`}</title>
              </circle>
            ) : null,
          )}
        </svg>
        <span className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-xl leading-none font-semibold text-ink">
            {total}
          </span>
          <span className="mt-0.5 text-[10px] text-ink-3">total</span>
        </span>
      </div>

      {/* Leyenda: icono + etiqueta + cifra. El color nunca informa por sí solo. */}
      <ul className="space-y-2">
        {segments.map(({ label, value, color, icon: Icon }) => (
          <li key={label} className="flex items-center gap-2.5 text-xs">
            <span
              aria-hidden
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: color }}
            />
            <Icon className="h-3.5 w-3.5 shrink-0 text-ink-3" />
            <span className="text-ink-2">{label}</span>
            <span className="tnum font-semibold text-ink">{value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

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
      <div className="flex h-64 items-center justify-center gap-2 text-ink-3">
        <RefreshCw className="h-5 w-5 animate-spin" />
        <span className="text-sm">Cargando métricas...</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex h-64 flex-col items-center justify-center text-center text-ink-3">
        <BarChart3 className="mb-3 h-10 w-10 opacity-40" />
        <p className="text-sm font-medium text-ink-2">
          No se pudieron cargar las métricas
        </p>
        <p className="mt-1 text-xs">
          Verifica que el backend esté corriendo en :8000
        </p>
      </div>
    );
  }

  const docStatuses = Object.entries(data.by_status);
  const sugTypes = Object.entries(data.suggestions_by_type);
  const maxDocStatus = Math.max(...Object.values(data.by_status), 1);
  const maxSugType = Math.max(...Object.values(data.suggestions_by_type), 1);
  const pending = data.suggestions_by_status["pending"] ?? 0;
  const approved = data.suggestions_by_status["approved"] ?? 0;
  const rejected = data.suggestions_by_status["rejected"] ?? 0;

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      {/* KPIs */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          icon={FileText}
          label="Documentos totales"
          value={data.total_documents}
          tone="bg-info-soft text-info-fg"
        />
        <StatCard
          icon={BarChart3}
          label="Sugerencias totales"
          value={data.total_suggestions}
          tone="bg-brand-soft text-brand-soft-fg"
        />
        <StatCard
          icon={CheckCircle2}
          label="Aprobadas"
          value={approved}
          tone="bg-success-soft text-success-fg"
        />
        <StatCard
          icon={TrendingUp}
          label="Tasa de aprobación"
          value={`${Math.round(data.approval_rate * 100)}%`}
          tone="bg-success-soft text-success-fg"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Documentos por estado */}
        <div className="card p-5">
          <h2 className="section-title mb-4">Documentos por estado</h2>
          <div className="space-y-3">
            {docStatuses.length === 0 ? (
              <p className="text-xs text-ink-3">Sin datos aún</p>
            ) : (
              docStatuses.map(([status, count]) => (
                <BarRow
                  key={status}
                  label={STATUS_LABEL[status] ?? status.replace("_", " ")}
                  value={count}
                  max={maxDocStatus}
                  total={data.total_documents}
                />
              ))
            )}
          </div>
        </div>

        {/* Sugerencias por tipo */}
        <div className="card p-5">
          <h2 className="section-title mb-4">Sugerencias por tipo</h2>
          <div className="space-y-3">
            {sugTypes.length === 0 ? (
              <p className="text-xs text-ink-3">Sin sugerencias aún</p>
            ) : (
              sugTypes.map(([type, count]) => (
                <BarRow
                  key={type}
                  label={TYPE_LABEL[type] ?? type}
                  value={count}
                  max={maxSugType}
                  total={data.total_suggestions}
                />
              ))
            )}
          </div>
        </div>

        {/* Estado de sugerencias */}
        <div className="card p-5">
          <h2 className="section-title mb-4">Estado de sugerencias</h2>
          <StatusDonut
            total={data.total_suggestions}
            segments={[
              {
                label: "Pendientes",
                value: pending,
                color: "var(--c-warning)",
                icon: Clock,
              },
              {
                label: "Aprobadas",
                value: approved,
                color: "var(--c-success)",
                icon: CheckCircle2,
              },
              {
                label: "Rechazadas",
                value: rejected,
                color: "var(--c-danger)",
                icon: XCircle,
              },
            ]}
          />
        </div>

        {/* Acciones pendientes */}
        <div className="card p-5">
          <h2 className="section-title mb-4">Acciones pendientes</h2>
          <div className="space-y-2.5">
            {pending === 0 && (data.by_status["needs_review"] ?? 0) === 0 ? (
              <div className="note note-success">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                <span>No hay nada esperando tu revisión.</span>
              </div>
            ) : (
              <>
                {pending > 0 && (
                  <div className="note note-warning">
                    <Clock className="mt-0.5 h-4 w-4 shrink-0" />
                    <div>
                      <p className="font-semibold">
                        {pending} sugerencia{pending !== 1 ? "s" : ""} por revisar
                      </p>
                      <p className="mt-0.5 text-xs opacity-80">
                        Ve a Revisión para aprobar o rechazar
                      </p>
                    </div>
                  </div>
                )}
                {(data.by_status["needs_review"] ?? 0) > 0 && (
                  <div className="note note-info">
                    <FileText className="mt-0.5 h-4 w-4 shrink-0" />
                    <div>
                      <p className="font-semibold">
                        {data.by_status["needs_review"]} documento
                        {(data.by_status["needs_review"] ?? 0) !== 1 ? "s" : ""} sin
                        analizar
                      </p>
                      <p className="mt-0.5 text-xs opacity-80">
                        Esperando procesamiento del agente
                      </p>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {/* HU-32 — consumo de tokens y costo estimado */}
      <TokenUsagePanel />
    </div>
  );
}
