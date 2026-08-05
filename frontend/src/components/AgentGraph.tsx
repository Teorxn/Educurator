import { useEffect, useRef, useState } from "react";
import { Loader2, AlertCircle } from "lucide-react";
import mermaid from "mermaid";
import { getGraphDiagram } from "../api/analysis";
import { useTheme } from "../theme";

// Mermaid no lee variables CSS, así que el diagrama necesita su propia paleta
// por tema; si no, en oscuro quedan rellenos claros con texto oscuro sobre una
// tarjeta oscura, es decir, ilegible.
const MERMAID_THEME = {
  light: {
    primaryColor: "#f1ecfd",
    primaryTextColor: "#2f1d63",
    primaryBorderColor: "#6941d1",
    lineColor: "#8a8578",
    secondaryColor: "#f1efe9",
    tertiaryColor: "#ffffff",
    background: "#ffffff",
    mainBkg: "#f1ecfd",
    textColor: "#1b1a16",
  },
  dark: {
    primaryColor: "#241f35",
    primaryTextColor: "#e5dcfd",
    primaryBorderColor: "#9575ef",
    lineColor: "#817d8e",
    secondaryColor: "#201f28",
    tertiaryColor: "#17161d",
    background: "#17161d",
    mainBkg: "#241f35",
    textColor: "#f4f2ef",
  },
} as const;

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
  const { resolved } = useTheme();

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        // Reinicializar en cada cambio de tema: mermaid congela las variables
        // en el momento del render, no las relee del DOM.
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "loose",
          theme: "base",
          themeVariables: {
            ...MERMAID_THEME[resolved],
            fontFamily: '"Plus Jakarta Sans Variable", ui-sans-serif, sans-serif',
            fontSize: "13px",
          },
          flowchart: { curve: "basis", htmlLabels: true },
        });

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
  }, [resolved]);

  return (
    <div className="card p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-ink-3">
          Generado del grafo LangGraph compilado — nodos y aristas reales
        </p>
        {llm && <span className="chip chip-brand">LLM: {llm}</span>}
      </div>

      {loading && (
        <div className="flex h-40 items-center justify-center gap-2 text-ink-3">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span className="text-sm">Generando diagrama del grafo...</span>
        </div>
      )}

      {error && (
        <div className="note note-danger">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <div ref={containerRef} className="flex justify-center overflow-x-auto" />
    </div>
  );
}
