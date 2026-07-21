import { useState } from "react";
import {
  Upload,
  Cpu,
  CheckSquare,
  BarChart3,
  MessageSquare,
  X,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

const SEEN_KEY = "educurator_tutorial_seen";

/** Marca de si el usuario ya vio el tutorial (persistente entre sesiones). */
export function hasSeenTutorial(): boolean {
  return localStorage.getItem(SEEN_KEY) === "1";
}

export function markTutorialSeen(): void {
  localStorage.setItem(SEEN_KEY, "1");
}

const STEPS = [
  {
    icon: Upload,
    title: "1. Sube tus documentos",
    color: "text-violet-600 bg-violet-50",
    body: [
      "Desde «Subir documento» arrastra uno o varios archivos (PDF, DOCX o TXT, hasta 50 MB cada uno).",
      "Puedes subir hasta 10 documentos a la vez: cada uno se valida por separado, así que un archivo inválido no cancela los demás.",
      "En «Documentos de referencia» puedes cargar guías, lineamientos o buenas prácticas: el agente los usará como criterio para evaluar tu material.",
    ],
  },
  {
    icon: Cpu,
    title: "2. El agente procesa el material",
    color: "text-blue-600 bg-blue-50",
    body: [
      "Cada documento pasa por la cola y verás su estado en tiempo real: En cola → Procesando → Analizado.",
      "El agente extrae el texto, lo divide en fragmentos, detecta redundancias y contradicciones, lo contrasta con tus documentos de referencia y genera preguntas frecuentes.",
      "Si algo falla, el documento queda en estado Error con la descripción del problema y puedes reintentarlo.",
    ],
  },
  {
    icon: CheckSquare,
    title: "3. Revisa y decide",
    color: "text-green-600 bg-green-50",
    body: [
      "En «Revisión» verás cada sugerencia con su nivel de confianza, el razonamiento del agente y la evidencia: los fragmentos exactos del documento que la respaldan.",
      "Apruebas o rechazas cada una. Al rechazar debes indicar el motivo: el agente aprende de esos motivos para mejorar sus próximas sugerencias.",
      "Un documento solo puede aprobarse cuando todas sus sugerencias han sido revisadas.",
    ],
  },
  {
    icon: MessageSquare,
    title: "4. Pregunta en lenguaje natural",
    color: "text-amber-600 bg-amber-50",
    body: [
      "En «Preguntar» puedes hacer preguntas sobre tus documentos y obtener respuestas fundamentadas.",
      "Cada respuesta cita las fuentes: qué documento y qué fragmento la respalda.",
      "Si la información no está en tus documentos, el sistema te lo dice en lugar de inventarla.",
    ],
  },
  {
    icon: BarChart3,
    title: "5. Consulta las métricas",
    color: "text-pink-600 bg-pink-50",
    body: [
      "En «Analytics» revisas el estado general: documentos, sugerencias por tipo y tasa de aprobación.",
      "También verás el consumo de tokens y el costo estimado del análisis con IA.",
      "En «Ejecuciones del agente» encuentras el historial de cada corrida y el diagrama del flujo de trabajo.",
    ],
  },
];

interface TutorialModalProps {
  open: boolean;
  onClose: () => void;
}

/** HU-21 — Tutorial de uso, accesible desde cualquier sección. */
export default function TutorialModal({ open, onClose }: TutorialModalProps) {
  const [step, setStep] = useState(0);

  if (!open) return null;

  const current = STEPS[step];
  const Icon = current.icon;
  const isLast = step === STEPS.length - 1;

  const close = () => {
    markTutorialSeen();
    setStep(0);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="fixed inset-0 bg-black/40" onClick={close} />

      <div className="relative bg-white rounded-2xl shadow-xl max-w-lg w-full z-10 overflow-hidden">
        {/* Header */}
        <div className="flex items-start justify-between p-5 pb-3">
          <div className="flex items-center gap-3">
            <span className={`p-2 rounded-xl ${current.color}`}>
              <Icon className="w-5 h-5" />
            </span>
            <div>
              <h3 className="text-base font-semibold text-gray-900">
                {current.title}
              </h3>
              <p className="text-xs text-gray-400 mt-0.5">
                Paso {step + 1} de {STEPS.length}
              </p>
            </div>
          </div>
          <button
            onClick={close}
            className="p-1 rounded-md text-gray-400 hover:text-gray-600"
            aria-label="Cerrar tutorial"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 pb-4 space-y-2.5">
          {current.body.map((p, i) => (
            <p key={i} className="text-sm text-gray-600 leading-relaxed">
              {p}
            </p>
          ))}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 px-5 py-4 bg-gray-50 border-t border-gray-100">
          <div className="flex items-center gap-1.5">
            {STEPS.map((_, i) => (
              <button
                key={i}
                onClick={() => setStep(i)}
                aria-label={`Ir al paso ${i + 1}`}
                className={`h-1.5 rounded-full transition-all ${
                  i === step ? "w-5 bg-violet-600" : "w-1.5 bg-gray-300"
                }`}
              />
            ))}
          </div>

          <div className="flex items-center gap-2">
            {step > 0 && (
              <button
                onClick={() => setStep((s) => s - 1)}
                className="flex items-center gap-1 text-sm text-gray-600 hover:text-gray-800 px-3 py-1.5 rounded-lg"
              >
                <ChevronLeft className="w-4 h-4" />
                Anterior
              </button>
            )}
            {isLast ? (
              <button
                onClick={close}
                className="bg-violet-600 hover:bg-violet-700 text-white text-sm font-medium px-4 py-1.5 rounded-lg"
              >
                Empezar
              </button>
            ) : (
              <button
                onClick={() => setStep((s) => s + 1)}
                className="flex items-center gap-1 bg-violet-600 hover:bg-violet-700 text-white text-sm font-medium px-4 py-1.5 rounded-lg"
              >
                Siguiente
                <ChevronRight className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
