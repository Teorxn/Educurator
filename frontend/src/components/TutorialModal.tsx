import {
  Upload,
  BookOpen,
  Sparkles,
  CheckSquare,
  MessageSquare,
  BarChart3,
  Activity,
} from "lucide-react";
import Tour from "./Tour";
import type { TourStep } from "./Tour";

const SEEN_KEY = "educurator_tutorial_seen";

/** Marca de si el usuario ya vio el tutorial (persistente entre sesiones). */
export function hasSeenTutorial(): boolean {
  return localStorage.getItem(SEEN_KEY) === "1";
}

export function markTutorialSeen(): void {
  localStorage.setItem(SEEN_KEY, "1");
}

/**
 * HU-21 — Tutorial de uso. Recorre la interfaz real señalando, en cada
 * sección, el control con el que hay que actuar: el orden de los pasos es el
 * camino mínimo para que el sistema produzca resultados (subir → analizar →
 * revisar → consultar).
 */
const STEPS: TourStep[] = [
  {
    route: "/docs",
    target: '[data-tour="nav-docs"]',
    icon: Upload,
    title: "Todo empieza en Documentos",
    body: "Aquí vive el material del curso: lo que subas es lo que el agente va a revisar.",
    action: "Abre «Documentos» en el menú lateral.",
  },
  {
    route: "/docs",
    target: '[data-tour="upload-docs"]',
    icon: Upload,
    title: "Sube tu material",
    body: "PDF, DOCX o TXT, hasta 50 MB cada uno y 10 documentos por carga. Cada archivo se valida por separado, así que uno inválido no cancela los demás.",
    action: "Despliega «Subir documentos» y arrastra tus archivos.",
  },
  {
    route: "/docs",
    target: '[data-tour="tab-reference"]',
    icon: BookOpen,
    title: "Añade tus criterios",
    body: "Los documentos de referencia —reglamentos, guías, buenas prácticas— son con lo que el agente contrasta tu material. Sin ellos sólo detecta problemas internos.",
    action: "Entra en «De referencia» y sube al menos una guía.",
  },
  {
    route: "/docs",
    target: '[data-tour="analyze-all"]',
    icon: Sparkles,
    title: "Lanza el análisis",
    body: "El agente extrae el texto, lo divide en fragmentos, busca redundancias y contradicciones, lo compara con tus referencias y propone preguntas frecuentes. Verás el estado cambiar de En cola a Procesando y Analizado.",
    action: "Pulsa «Analizar todo» cuando tengas documentos cargados.",
  },
  {
    route: "/review",
    target: '[data-tour="review-list"]',
    icon: CheckSquare,
    title: "Tú decides qué se aplica",
    body: "Cada sugerencia trae su confianza, el razonamiento del agente y los fragmentos que la respaldan. Al rechazar debes indicar el motivo: el agente aprende de esos motivos. Un documento sólo se aprueba cuando no le quedan sugerencias sin revisar.",
    action: "Aprueba o rechaza las sugerencias pendientes.",
  },
  {
    route: "/chat",
    target: '[data-tour="chat-input"]',
    icon: MessageSquare,
    title: "Pregunta en lenguaje natural",
    body: "Las respuestas citan siempre el documento y el fragmento que las respalda. Si algo no está en tus documentos, el sistema lo dice en lugar de inventarlo.",
    action: "Escribe una pregunta sobre tu material.",
  },
  {
    route: "/agent-runs",
    target: '[data-tour="agent-graph"]',
    icon: Activity,
    title: "Mira qué hizo el agente",
    body: "En «Ejecuciones» tienes el historial de cada corrida y el grafo real del flujo de trabajo, nodo a nodo.",
    action: "Abre «Ver grafo del agente».",
  },
  {
    route: "/analytics",
    target: '[data-tour="nav-analytics"]',
    icon: BarChart3,
    title: "Y cómo va todo",
    body: "Métricas reúne el estado general: documentos, sugerencias por tipo, tasa de aprobación y el consumo de tokens con su costo estimado.",
  },
];

interface TutorialModalProps {
  open: boolean;
  onClose: () => void;
}

export default function TutorialModal({ open, onClose }: TutorialModalProps) {
  const close = () => {
    markTutorialSeen();
    onClose();
  };

  return <Tour open={open} steps={STEPS} onClose={close} />;
}
