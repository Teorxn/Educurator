import { useEffect, useRef, useState } from "react";
import { Loader2, AlertCircle } from "lucide-react";
import mermaid from "mermaid";
import { getGraphDiagram } from "../api/analysis";

mermaid.initialize({
  startOnLoad: false,
  theme: "base",
  themeVariables: {
    primaryColor: "#ede9fe", // violet-100
    primaryTextColor: "#4c1d95", // violet-900
    primaryBorderColor: "#8b5cf6", // violet-500
    lineColor: "#a78bfa", // violet-400
    secondaryColor: "#f5f3ff",
    tertiaryColor: "#ffffff",
    fontFamily: "ui-sans-serif, system-ui, sans-serif",
    fontSize: "13px",
  },
  flowchart: { curve: "basis", htmlLabels: true },
});

/**
 * Renderiza el grafo LangGraph del agente (diagrama Mermaid generado
 * desde el grafo COMPILADO en el backend — siempre refleja los nodos
 * y aristas reales, incluyendo ramas condicionales).
 */
export default function AgentGraph() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [llm, setLlm] = useState("");

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const { data } = await getGraphDiagram();
        if (cancelled) return;
        setLlm(data.llm);

        const { svg } = await mermaid.render("agent-graph-svg", data.mermaid);
        if (cancelled || !containerRef.current) return;
        containerRef.current.innerHTML = svg;

        // El SVG debe escalar al ancho disponible
        const el = containerRef.current.querySelector("svg");
        if (el) {
          el.style.maxWidth = "100%";
          el.style.height = "auto";
        }
      } catch {
        if (!cancelled) setError("No se pudo cargar el diagrama del grafo.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-40 text-gray-400 gap-2">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span className="text-sm">Generando diagrama del grafo...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3">
        <AlertCircle className="w-4 h-4 shrink-0" />
        {error}
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <p className="text-xs text-gray-400">
          Generado del grafo LangGraph compilado — nodos y aristas reales
        </p>
        {llm && (
          <span className="text-xs font-medium text-violet-600 bg-violet-50 px-2 py-0.5 rounded-full">
            LLM: {llm}
          </span>
        )}
      </div>
      <div ref={containerRef} className="overflow-x-auto flex justify-center" />
    </div>
  );
}
