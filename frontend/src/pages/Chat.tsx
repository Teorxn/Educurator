import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  Send,
  Loader2,
  MessageSquare,
  ChevronDown,
  ChevronUp,
  FileText,
  AlertCircle,
  Sparkles,
} from "lucide-react";
import { askChat } from "../api/account";
import type { ChatAnswer } from "../api/account";
import { getDocs } from "../api/docs";
import type { Document } from "../api/docs";

interface Turn {
  id: string;
  question: string;
  answer?: ChatAnswer;
  error?: string;
  loading: boolean;
}

const EXAMPLES = [
  "¿Cuáles son los criterios de evaluación del curso?",
  "¿Qué requisitos debe cumplir la entrega final?",
  "Resume los temas principales del material",
];

/** HU-31 — Consultar información mediante lenguaje natural (RAG con fuentes). */
export default function Chat() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [docFilter, setDocFilter] = useState<string>("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getDocs({ limit: 100 })
      .then(({ data }) => setDocuments(data.items))
      .catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  const ask = async (text: string) => {
    const q = text.trim();
    if (!q || sending) return;

    const id = `${Date.now()}`;
    setTurns((prev) => [...prev, { id, question: q, loading: true }]);
    setQuestion("");
    setSending(true);

    try {
      const { data } = await askChat(q, docFilter ? [docFilter] : undefined);
      setTurns((prev) =>
        prev.map((t) => (t.id === id ? { ...t, answer: data, loading: false } : t)),
      );
    } catch (e) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "No se pudo obtener una respuesta. Intenta de nuevo.";
      setTurns((prev) =>
        prev.map((t) => (t.id === id ? { ...t, error: detail, loading: false } : t)),
      );
    } finally {
      setSending(false);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    ask(question);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)] max-w-4xl">
      {/* Filtro por documento */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <label className="text-xs text-gray-500">Buscar en:</label>
        <select
          value={docFilter}
          onChange={(e) => setDocFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-violet-400 max-w-xs"
        >
          <option value="">Todos mis documentos</option>
          {documents.map((d) => (
            <option key={d.id} value={d.id}>
              {d.filename}
            </option>
          ))}
        </select>
        {turns.length > 0 && (
          <button
            onClick={() => setTurns([])}
            className="ml-auto text-xs text-gray-500 hover:text-gray-700"
          >
            Limpiar conversación
          </button>
        )}
      </div>

      {/* Historial de la sesión */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        {turns.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center px-4">
            <div className="w-14 h-14 bg-violet-50 rounded-2xl flex items-center justify-center mb-4">
              <MessageSquare className="w-7 h-7 text-violet-500" />
            </div>
            <p className="text-gray-700 font-medium">
              Pregunta sobre tus documentos
            </p>
            <p className="text-sm text-gray-400 mt-1 max-w-md">
              Las respuestas se basan únicamente en el contenido que has subido,
              y siempre citan el documento y fragmento de origen.
            </p>
            <div className="flex flex-col gap-2 mt-5 w-full max-w-md">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  onClick={() => ask(ex)}
                  className="flex items-center gap-2 text-left text-sm text-gray-600 bg-white border border-gray-200 hover:border-violet-300 hover:bg-violet-50/40 rounded-xl px-3.5 py-2.5 transition-colors"
                >
                  <Sparkles className="w-3.5 h-3.5 text-violet-400 shrink-0" />
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((t) => (
          <div key={t.id} className="space-y-2">
            {/* Pregunta */}
            <div className="flex justify-end">
              <div className="bg-violet-600 text-white text-sm rounded-2xl rounded-br-sm px-4 py-2.5 max-w-[80%]">
                {t.question}
              </div>
            </div>

            {/* Respuesta */}
            <div className="flex justify-start">
              <div className="bg-white border border-gray-200 rounded-2xl rounded-bl-sm px-4 py-3 max-w-[85%] w-full">
                {t.loading && (
                  <div className="flex items-center gap-2 text-gray-400 text-sm">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Buscando en tus documentos...
                  </div>
                )}

                {t.error && (
                  <div className="flex items-start gap-2 text-sm text-red-600">
                    <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                    {t.error}
                  </div>
                )}

                {t.answer && (
                  <>
                    <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">
                      {t.answer.answer}
                    </p>

                    {t.answer.has_context && (
                      <div className="flex items-center gap-3 mt-2.5 flex-wrap">
                        <span className="text-xs font-medium text-violet-600 bg-violet-50 px-2 py-0.5 rounded-full">
                          Confianza: {Math.round(t.answer.confidence * 100)}%
                        </span>
                        {t.answer.model && (
                          <span className="text-xs text-gray-400">
                            {t.answer.model}
                          </span>
                        )}
                      </div>
                    )}

                    {/* Fuentes desplegables */}
                    {t.answer.sources.length > 0 && (
                      <div className="mt-3">
                        <button
                          onClick={() =>
                            setExpanded((p) => ({ ...p, [t.id]: !p[t.id] }))
                          }
                          className="flex items-center gap-1.5 text-xs font-medium text-violet-600 hover:text-violet-700"
                        >
                          <FileText className="w-3.5 h-3.5" />
                          {expanded[t.id] ? "Ocultar" : "Ver"} fuentes (
                          {t.answer.sources.length})
                          {expanded[t.id] ? (
                            <ChevronUp className="w-3 h-3" />
                          ) : (
                            <ChevronDown className="w-3 h-3" />
                          )}
                        </button>

                        {expanded[t.id] && (
                          <div className="mt-2 space-y-2">
                            {t.answer.sources.map((s, i) => (
                              <div
                                key={`${s.doc_id}-${s.chunk_index}-${i}`}
                                className="bg-gray-50 border border-gray-200 rounded-lg p-3"
                              >
                                <div className="flex items-center justify-between mb-1 gap-2">
                                  <span className="text-xs font-medium text-gray-600 truncate">
                                    {s.doc_name} · fragmento {s.chunk_index}
                                  </span>
                                  <span className="text-xs text-gray-400 shrink-0">
                                    {Math.round(s.similarity * 100)}% afinidad
                                  </span>
                                </div>
                                <p className="text-xs text-gray-600 leading-relaxed">
                                  {s.excerpt}
                                </p>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Entrada */}
      <form onSubmit={onSubmit} className="flex items-center gap-2 mt-4">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Escribe tu pregunta..."
          disabled={sending}
          className="flex-1 border border-gray-200 rounded-xl px-4 py-2.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-violet-400 focus:border-transparent disabled:bg-gray-50"
        />
        <button
          type="submit"
          disabled={!question.trim() || sending}
          className="flex items-center justify-center w-11 h-11 bg-violet-600 hover:bg-violet-700 disabled:bg-violet-300 text-white rounded-xl transition-colors shrink-0"
          aria-label="Enviar pregunta"
        >
          {sending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Send className="w-4 h-4" />
          )}
        </button>
      </form>
    </div>
  );
}
