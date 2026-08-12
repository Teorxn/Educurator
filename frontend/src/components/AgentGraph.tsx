import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  AlertCircle,
  Loader2,
  Maximize2,
  Minus,
  Plus,
  X,
} from "lucide-react";
import mermaid from "mermaid";
import { getGraphDiagram } from "../api/analysis";
import { useTheme } from "../theme";
import type { ResolvedTheme } from "../theme";
import Modal from "./Modal";

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

// LangGraph cierra `draw_mermaid()` con classDef de colores fijos
// (`fill:#f2f0ff`, `fill:#bfb6fc`). En tema oscuro eso deja relleno casi blanco
// con el texto claro del tema encima: ~1.2:1 de contraste, ilegible. Se
// descartan y se ponen los del tema activo.
const CLASS_DEFS: Record<ResolvedTheme, string[]> = {
  light: [
    "classDef default fill:#f1ecfd,stroke:#6941d1,stroke-width:1px,color:#2f1d63,line-height:1.3",
    "classDef first fill:#ffffff,stroke:#6941d1,stroke-width:1px,color:#1b1a16",
    "classDef last fill:#6941d1,stroke:#6941d1,color:#ffffff",
  ],
  dark: [
    "classDef default fill:#241f35,stroke:#9575ef,stroke-width:1px,color:#e5dcfd,line-height:1.3",
    "classDef first fill:#17161d,stroke:#9575ef,stroke-width:1px,color:#f4f2ef",
    "classDef last fill:#9575ef,stroke:#9575ef,color:#17161d",
  ],
};

function themeDiagram(source: string, theme: ResolvedTheme): string {
  const body = source
    .split("\n")
    .filter((line) => !/^\s*classDef\s+(default|first|last)\b/.test(line))
    .join("\n")
    .trimEnd();
  return `${body}\n\t${CLASS_DEFS[theme].join("\n\t")}\n`;
}

// Contador para ids únicos: React StrictMode monta el efecto dos veces en
// dev y dos mermaid.render concurrentes con el MISMO id se pisan entre sí
// (uno borra el DOM temporal del otro → SVG vacío).
let renderSeq = 0;

const ZOOM_MIN = 0.4;
const ZOOM_MAX = 2;

interface Size {
  width: number;
  height: number;
}

/**
 * Dibuja un diagrama Mermaid a tamaño legible.
 *
 * Mermaid emite un `viewBox` mucho mayor que el contenido real (para este grafo,
 * 2110×2039 frente a 674×889 de dibujo): al encajar ese lienzo en el ancho del
 * contenedor todo se reducía al ~40 % y las etiquetas de 13 px acababan
 * dibujadas a 5 px. Por eso se recalcula el `viewBox` a partir de la caja real
 * del contenido y el zoom se controla aparte.
 */
export function AgentDiagram({ source }: { source: string }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [natural, setNatural] = useState<Size | null>(null);
  const [zoom, setZoom] = useState(1);
  const [error, setError] = useState("");
  const { resolved } = useTheme();

  // Ajusta el diagrama al ancho disponible sin bajar de un tamaño legible.
  const fit = useCallback((size: Size) => {
    const available = boxRef.current?.clientWidth ?? size.width;
    return Math.min(1, Math.max(0.55, (available - 24) / size.width));
  }, []);

  useEffect(() => {
    let cancelled = false;

    const draw = async () => {
      setError("");
      try {
        // Reinicializar en cada cambio de tema: mermaid congela las variables
        // en el momento del render, no las relee del DOM.
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "loose",
          theme: "base",
          themeVariables: {
            ...MERMAID_THEME[resolved],
            fontFamily:
              '"Plus Jakarta Sans Variable", ui-sans-serif, sans-serif',
            fontSize: "13px",
          },
          flowchart: { curve: "basis", htmlLabels: true },
        });

        renderSeq += 1;
        const { svg } = await mermaid.render(
          `agent-graph-${renderSeq}-${Date.now()}`,
          themeDiagram(source, resolved),
        );

        if (cancelled || !canvasRef.current) return;
        if (!svg || !svg.includes("<svg")) {
          throw new Error("mermaid retornó un SVG vacío");
        }
        canvasRef.current.innerHTML = svg;

        const el = canvasRef.current.querySelector("svg");
        const root = el?.querySelector("g");
        if (!el || !root) throw new Error("SVG sin contenido");

        const box = root.getBBox();
        const pad = 16;
        const size = {
          width: Math.ceil(box.width + pad * 2),
          height: Math.ceil(box.height + pad * 2),
        };
        el.setAttribute(
          "viewBox",
          `${box.x - pad} ${box.y - pad} ${size.width} ${size.height}`,
        );
        el.style.display = "block";
        setNatural(size);
        setZoom(fit(size));
      } catch (e) {
        console.error("Error renderizando el grafo del agente:", e);
        if (!cancelled) setError("No se pudo renderizar el diagrama.");
      }
    };

    draw();
    return () => {
      cancelled = true;
    };
  }, [source, resolved, fit]);

  // El zoom se aplica sobre el SVG ya dibujado: no hace falta volver a pasar
  // por mermaid, que es lo caro.
  useEffect(() => {
    const el = canvasRef.current?.querySelector("svg");
    if (!el || !natural) return;
    el.style.width = `${Math.round(natural.width * zoom)}px`;
    el.style.height = `${Math.round(natural.height * zoom)}px`;
    el.style.maxWidth = "none";
  }, [zoom, natural]);

  const step = (delta: number) =>
    setZoom((z) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, +(z + delta).toFixed(2))));

  if (error) {
    return (
      <div className="note note-danger">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-end gap-1">
        <button
          onClick={() => step(-0.2)}
          disabled={zoom <= ZOOM_MIN}
          className="btn-icon h-8 w-8"
          aria-label="Alejar"
          title="Alejar"
        >
          <Minus className="h-4 w-4" />
        </button>
        <span className="tnum w-12 text-center text-xs text-ink-3">
          {Math.round(zoom * 100)}%
        </span>
        <button
          onClick={() => step(0.2)}
          disabled={zoom >= ZOOM_MAX}
          className="btn-icon h-8 w-8"
          aria-label="Acercar"
          title="Acercar"
        >
          <Plus className="h-4 w-4" />
        </button>
        <button
          onClick={() => natural && setZoom(fit(natural))}
          className="btn-icon h-8 w-8"
          aria-label="Ajustar al ancho"
          title="Ajustar al ancho"
        >
          <Maximize2 className="h-4 w-4" />
        </button>
      </div>

      <div
        ref={boxRef}
        className="max-h-[65vh] overflow-auto rounded-field border border-line bg-surface-2 p-3"
      >
        <div ref={canvasRef} className="w-max" />
      </div>
    </div>
  );
}

interface AgentGraphModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Grafo LangGraph del agente en una ventana propia: el diagrama es alto y
 * necesita su espacio, así que empujaba la tabla de ejecuciones fuera de
 * pantalla cuando se mostraba en la misma página.
 */
export default function AgentGraphModal({
  open,
  onClose,
}: AgentGraphModalProps) {
  const titleId = useId();
  const [source, setSource] = useState("");
  const [llm, setLlm] = useState("");
  const [error, setError] = useState("");

  // El diagrama se pide una sola vez y se conserva: reabrir la ventana no
  // vuelve a llamar al backend.
  useEffect(() => {
    if (!open || source || error) return;
    let cancelled = false;

    getGraphDiagram()
      .then(({ data }) => {
        if (cancelled) return;
        setSource(data.mermaid);
        setLlm(data.llm);
      })
      .catch(() => {
        if (!cancelled) setError("No se pudo obtener el grafo del agente.");
      });

    return () => {
      cancelled = true;
    };
  }, [open, source, error]);

  const loading = open && !source && !error;

  return (
    <Modal open={open} onClose={onClose} labelledBy={titleId} size="xl">
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0">
          <h2 id={titleId} className="text-base font-semibold text-ink">
            Grafo del agente
          </h2>
          <p className="mt-0.5 text-xs text-ink-3">
            Generado del grafo LangGraph compilado — nodos y aristas reales
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {llm && <span className="chip chip-brand">LLM: {llm}</span>}
          <button
            onClick={onClose}
            className="btn-icon h-8 w-8"
            aria-label="Cerrar"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="p-5">
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
        {source && <AgentDiagram source={source} />}
      </div>
    </Modal>
  );
}
