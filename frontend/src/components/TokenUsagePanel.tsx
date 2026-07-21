import { useEffect, useState } from "react";
import { Coins, Cpu, Loader2, TrendingUp, Info } from "lucide-react";
import { getTokenAnalytics } from "../api/account";
import type { TokenAnalytics } from "../api/account";

const OPERATION_LABEL: Record<string, string> = {
  faq_generation: "Generación de FAQs",
  faq_single: "FAQ individual",
  reference_comparison: "Comparación con referencias",
  chat: "Preguntas (chat)",
  agent: "Agente ReAct",
  inconsistency: "Detección de inconsistencias",
};

function fmtNumber(n: number) {
  return new Intl.NumberFormat("es").format(n);
}

function fmtUsd(n: number) {
  return `$${n.toFixed(n < 0.01 ? 5 : 2)}`;
}

/** HU-32 — Consumo de IA: tokens y costo estimado. */
export default function TokenUsagePanel() {
  const [data, setData] = useState<TokenAnalytics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getTokenAnalytics(30)
      .then(({ data }) => setData(data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-6 flex items-center justify-center gap-2 text-gray-400">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span className="text-sm">Cargando consumo de IA...</span>
      </div>
    );
  }

  if (!data) return null;

  const maxDaily = Math.max(1, ...data.daily.map((d) => d.tokens));
  const operations = Object.entries(data.by_operation).sort(
    (a, b) => b[1].tokens - a[1].tokens,
  );
  const models = Object.entries(data.by_model);

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
          <Cpu className="w-4 h-4 text-violet-500" />
          Consumo de IA
        </h2>
        <span
          className="inline-flex items-center gap-1 text-xs text-gray-400"
          title={`Tarifas: $${data.rates.input_per_1k}/1k entrada · $${data.rates.output_per_1k}/1k salida`}
        >
          <Info className="w-3 h-3" />
          Costos estimados · últimos {data.period_days} días
        </span>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="border border-gray-100 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">Tokens totales</p>
          <p className="text-xl font-semibold text-gray-900">
            {fmtNumber(data.total_tokens)}
          </p>
          <p className="text-[11px] text-gray-400 mt-0.5">
            {fmtNumber(data.input_tokens)} in · {fmtNumber(data.output_tokens)}{" "}
            out
          </p>
        </div>
        <div className="border border-gray-100 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">Costo estimado</p>
          <p className="text-xl font-semibold text-gray-900">
            {fmtUsd(data.total_cost_usd)}
          </p>
          <p className="text-[11px] text-gray-400 mt-0.5">
            {data.calls} llamada{data.calls !== 1 ? "s" : ""} al modelo
          </p>
        </div>
        <div className="border border-gray-100 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">Último análisis</p>
          <p className="text-xl font-semibold text-gray-900">
            {fmtNumber(data.last_run.total_tokens)}
          </p>
          <p className="text-[11px] text-gray-400 mt-0.5">
            {fmtUsd(data.last_run.cost_usd)}
          </p>
        </div>
        <div className="border border-gray-100 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">Modelo</p>
          <p className="text-sm font-semibold text-gray-900 truncate">
            {models.length > 0 ? models[0][0] : "—"}
          </p>
          {models.length > 1 && (
            <p className="text-[11px] text-gray-400 mt-0.5">
              +{models.length - 1} más
            </p>
          )}
        </div>
      </div>

      {/* Gráfico diario */}
      {data.daily.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-600 mb-2 flex items-center gap-1.5">
            <TrendingUp className="w-3.5 h-3.5 text-gray-400" />
            Tokens por día
          </p>
          <div className="flex items-end gap-1 h-24">
            {data.daily.map((d) => (
              <div
                key={d.date}
                className="flex-1 bg-violet-100 hover:bg-violet-200 rounded-t transition-colors relative group"
                style={{
                  height: `${Math.max(4, (d.tokens / maxDaily) * 100)}%`,
                }}
                title={`${d.date}: ${fmtNumber(d.tokens)} tokens (${fmtUsd(d.cost_usd)})`}
              >
                <span className="sr-only">
                  {d.date}: {d.tokens} tokens
                </span>
              </div>
            ))}
          </div>
          <div className="flex justify-between text-[11px] text-gray-400 mt-1">
            <span>{data.daily[0]?.date}</span>
            <span>{data.daily[data.daily.length - 1]?.date}</span>
          </div>
        </div>
      )}

      {/* Desglose por operación */}
      {operations.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-600 mb-2 flex items-center gap-1.5">
            <Coins className="w-3.5 h-3.5 text-gray-400" />
            Por tipo de operación
          </p>
          <div className="space-y-1.5">
            {operations.map(([op, v]) => {
              const pct = data.total_tokens
                ? Math.round((v.tokens / data.total_tokens) * 100)
                : 0;
              return (
                <div key={op} className="flex items-center gap-3">
                  <span className="text-xs text-gray-600 w-48 shrink-0 truncate">
                    {OPERATION_LABEL[op] ?? op}
                  </span>
                  <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-violet-500 h-2 rounded-full"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-500 w-28 text-right shrink-0">
                    {fmtNumber(v.tokens)} · {fmtUsd(v.cost_usd)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {data.total_tokens === 0 && (
        <p className="text-sm text-gray-400 text-center py-2">
          Aún no hay consumo registrado. Sube un documento para que el agente lo
          analice.
        </p>
      )}
    </div>
  );
}
