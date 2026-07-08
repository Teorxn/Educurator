import { useEffect, useRef, useState } from "react";
import { Loader2, AlertCircle } from "lucide-react";
import mermaid from "mermaid";
import { getGraphDiagram } from "../api/analysis";

mermaid.initialize({
  startOnLoad: false,
  securityLevel: "loose",
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

// Contador para ids únicos: React StrictMode monta el efecto dos veces en
// dev y dos mermaid.render concurrentes con el MISMO id se pisan entre sí
// (uno borra el DOM temporal del otro → SVG vacío).
let renderSeq = 0;

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

        renderSeq += 1;
        const renderId = `agent-graph-${renderSeq}-${Date.now()}`;
        const { svg } = await mermaid.render(renderId, data.mermaid);

        if (cancelled || !containerRef.current) return;
        if (!svg || !svg.includes("<svg")) {
          throw new Error("mermaid retornó un SVG vacío");
        }
        containerRef.current.innerHTML = svg;

        // Sizing: mermaid emite el SVG con viewBox pero sin width/height
        // explícitos — sin esto el navegador puede colapsarlo a altura 0.
        const el = containerRef.current.querySelector("svg");
        if (el) {
          el.removeAttribute("height");
          el.style.width = "100%";
          el.style.maxWidth = "900px";
          el.style.height = "auto";
          el.style.display = "block";
        }
      } catch (e) {
        console.error("Error renderizando el grafo del agente:", e);
        if (!cancelled) {
          setError("No se pudo renderizar el diagrama del grafo.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    return () => {
      cancelled = true;
    };
  }, []);

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

      {loading && (
        <div className="flex items-center justify-center h-40 text-gray-400 gap-2">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span className="text-sm">Generando diagrama del grafo...</span>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      <div ref={containerRef} className="overflow-x-auto flex justify-center" />
    </div>
  );
}
