import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  Send,
  Loader2,
  MessageSquare,
  ChevronDown,
  ChevronUp,
  FileText,
  AlertCircle,
  ArrowRight,
  Sparkles,
  HelpCircle,
  Plus,
  Trash2,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Check,
  ShieldCheck,
  ShieldAlert,
} from "lucide-react";
import {
  askChat,
  getChatHistory,
  getConversations,
  renameConversation,
  deleteConversation,
} from "../api/account";
import type { ChatAnswer, Conversation } from "../api/account";
import { getDocs, getSuggestions } from "../api/docs";
import type { Document, Suggestion } from "../api/docs";
import ConfirmDialog from "../components/ConfirmDialog";

interface Turn {
  id: string;
  question: string;
  answer?: ChatAnswer;
  error?: string;
  loading: boolean;
}

/** Nombre legible de un documento (sin extensión ni separadores). */
function docTitle(filename: string): string {
  return filename
    .replace(/\.[a-z0-9]{2,5}$/i, "")
    .replace(/[_-]+/g, " ")
    .trim()
    .slice(0, 45);
}

interface ChatSuggestion {
  question: string;
  docId: string;
  docLabel: string;
}

/**
 * Chip de confianza: qué tan bien respaldada está la respuesta en los
 * documentos del docente.
 *
 * El porcentaje solo nunca fue suficiente. Un "62%" se lee como un reprobado
 * escolar cuando en realidad describe una respuesta bien fundamentada, así
 * que el número va acompañado de la etiqueta que lo interpreta (y, según el
 * sistema de diseño, el color nunca va solo: icono + texto siempre).
 */
function ConfidenceChip({
  confidence,
  available = true,
}: {
  confidence: number;
  available?: boolean;
}) {
  // Sin búsqueda vectorial no hay nada que medir: decirlo es más útil que
  // mostrar un porcentaje que no significa nada.
  if (!available) {
    return (
      <span
        className="chip chip-neutral"
        title="La respuesta se apoyó en el contenido del documento, pero sin búsqueda semántica no hay confianza que medir."
      >
        <HelpCircle className="h-3.5 w-3.5" />
        Confianza no medible
      </span>
    );
  }

  const pct = Math.round(confidence * 100);
  const { style, Icon, label } =
    pct >= 75
      ? { style: "chip-success", Icon: ShieldCheck, label: "alta" }
      : pct >= 50
        ? { style: "chip-info", Icon: ShieldCheck, label: "media" }
        : { style: "chip-warning", Icon: ShieldAlert, label: "baja" };

  return (
    <span
      className={`chip ${style}`}
      title={`Qué tan parecido es el contenido encontrado a tu pregunta. Confianza ${label}: revisa las fuentes citadas${
        pct < 50 ? " — aquí conviene especialmente verificarlas" : ""
      }.`}
    >
      <Icon className="h-3.5 w-3.5" />
      Confianza {label} · {pct}%
    </span>
  );
}

/** Documentos que el agente ya procesó (los únicos consultables). */
function analyzedDocs(documents: Document[]): Document[] {
  return documents.filter(
    (d) => d.status === "analyzed" || d.status === "approved",
  );
}

/** Documentos que aún están en la cola del agente: pronto serán consultables. */
function pendingDocs(documents: Document[]): Document[] {
  return documents.filter(
    (d) =>
      d.status === "queued" ||
      d.status === "processing" ||
      d.status === "needs_review",
  );
}

/**
 * Por qué no se puede preguntar todavía.
 *
 * El chat responde SÓLO con lo que hay indexado: sin documentos analizados no
 * tiene de dónde sacar una respuesta, así que en vez de dejar preguntar para
 * contestar «no encontré información» —que suena a que la pregunta está mal—
 * se bloquea la entrada y se explica qué falta.
 */
type ChatBlock = "sin-documentos" | "procesando" | "sin-analizar" | null;

function chatBlock(documents: Document[], loading: boolean): ChatBlock {
  if (loading) return null;
  if (analyzedDocs(documents).length > 0) return null;
  if (documents.length === 0) return "sin-documentos";
  if (pendingDocs(documents).length > 0) return "procesando";
  return "sin-analizar";
}

const BLOCK_COPY: Record<
  Exclude<ChatBlock, null>,
  { title: string; body: string; cta: string }
> = {
  "sin-documentos": {
    title: "Aún no tienes documentos que consultar",
    body: "El chat responde únicamente con el contenido de tu material, así que necesita al menos un documento analizado.",
    cta: "Subir documentos",
  },
  procesando: {
    title: "El agente está analizando tu material",
    body: "En cuanto termine de procesar los documentos podrás preguntarle. Suele tardar poco; el estado se ve en «Documentos».",
    cta: "Ver el estado",
  },
  "sin-analizar": {
    title: "Ninguno de tus documentos se pudo analizar",
    body: "Tienes documentos subidos, pero ninguno quedó indexado. Revisa su estado y reintenta el análisis para poder preguntar sobre ellos.",
    cta: "Revisar documentos",
  },
};

/**
 * Preguntas sugeridas GENÉRICAS a partir de los documentos ya analizados.
 * Se usan solo como respaldo cuando el agente todavía no generó FAQs reales.
 */
function buildGenericSuggestions(documents: Document[]): ChatSuggestion[] {
  const docs = analyzedDocs(documents).slice(0, 3);
  const plantillas = [
    "¿Cuáles son los puntos principales de este documento?",
    "Resume el contenido de este documento",
    "¿Qué requisitos o criterios establece este documento?",
  ];
  return docs.map((d, i) => ({
    question: plantillas[i % plantillas.length],
    docId: d.id,
    docLabel: docTitle(d.filename),
  }));
}

/**
 * Preguntas sugeridas DINÁMICAS: las FAQ que el agente generó a partir del
 * contenido real de cada documento y que un instructor ya aprobó (HU-14).
 */
function buildFaqSuggestions(
  faqs: Suggestion[],
  documents: Document[],
): ChatSuggestion[] {
  return faqs.slice(0, 5).map((s) => {
    const question = s.description.replace(/^Pregunta:\s*/i, "").trim();
    const docLabel =
      s.document_name ??
      docTitle(documents.find((d) => d.id === s.document_id)?.filename ?? "");
    return { question, docId: s.document_id, docLabel };
  });
}

/** Agrupa los hilos por antigüedad, como haría un cliente de correo. */
function groupByRecency(items: Conversation[]) {
  const now = Date.now();
  const DAY = 86_400_000;
  const groups: { label: string; items: Conversation[] }[] = [
    { label: "Hoy", items: [] },
    { label: "Últimos 7 días", items: [] },
    { label: "Anteriores", items: [] },
  ];
  for (const c of items) {
    const age = now - new Date(c.updated_at).getTime();
    if (age < DAY) groups[0].items.push(c);
    else if (age < 7 * DAY) groups[1].items.push(c);
    else groups[2].items.push(c);
  }
  return groups.filter((g) => g.items.length > 0);
}

function fmtDateTime(d: string) {
  return new Intl.DateTimeFormat("es", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(d));
}

/** HU-31 — Consultar información mediante lenguaje natural (RAG con fuentes). */
export default function Chat() {
  const navigate = useNavigate();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [docFilter, setDocFilter] = useState<string>("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [faqSuggestions, setFaqSuggestions] = useState<Suggestion[] | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const turnSeq = useRef(0);

  // ── Conversaciones ───────────────────────────────────────────────────────
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const [loadingThread, setLoadingThread] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const activeConversation = conversations.find((c) => c.id === activeId) ?? null;

  // Sugerencias dinámicas (FAQs reales) con respaldo genérico
  const suggestions: ChatSuggestion[] =
    faqSuggestions && faqSuggestions.length > 0
      ? buildFaqSuggestions(faqSuggestions, documents)
      : buildGenericSuggestions(documents);

  const block = chatBlock(documents, docsLoading);
  const canAsk = block === null && !docsLoading;
  // El selector sólo ofrece lo que de verdad se puede consultar; si el hilo
  // abierto apunta a otro documento, se conserva su opción para no dejar el
  // desplegable en blanco.
  const scopeOptions = analyzedDocs(documents);
  const activeScopeMissing =
    docFilter !== "" && !scopeOptions.some((d) => d.id === docFilter);

  const loadConversations = useCallback(async () => {
    try {
      const { data } = await getConversations();
      setConversations(data.items);
      return data.items;
    } catch {
      return [];
    }
  }, []);

  useEffect(() => {
    // category:"all" — el chat consulta tanto material del curso como el
    // corpus de referencia; el selector debe reflejar el mismo alcance
    getDocs({ limit: 100, category: "all" })
      .then(({ data }) => setDocuments(data.items))
      .catch(() => {})
      .finally(() => setDocsLoading(false));

    // HU-31 — preguntas predeterminadas dinámicas: FAQs reales ya aprobadas
    getSuggestions({ type: "faq", status: "approved", limit: 6 })
      .then(({ data }) => setFaqSuggestions(data.items))
      .catch(() => setFaqSuggestions([]));

    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  /** Carga los mensajes de un hilo y restaura su alcance por documento. */
  const openConversation = async (convo: Conversation) => {
    if (convo.id === activeId) return;
    setActiveId(convo.id);
    setDocFilter(convo.document_id ?? "");
    setLoadingThread(true);
    setTurns([]);
    try {
      const { data } = await getChatHistory({
        conversation_id: convo.id,
        limit: 100,
      });
      // El backend devuelve el hilo en orden cronológico
      setTurns(
        data.items.map((m) => ({
          id: m.id,
          question: m.question,
          loading: false,
          answer: {
            answer: m.answer,
            sources: m.sources,
            confidence: m.confidence,
            confidence_available: m.confidence_available,
            has_context: m.has_context,
            model: m.model,
            searched_documents: m.searched_documents,
          },
        })),
      );
    } catch {
      setTurns([]);
    } finally {
      setLoadingThread(false);
    }
  };

  const startNewConversation = () => {
    setActiveId(null);
    setTurns([]);
    setQuestion("");
  };

  const handleRename = async (id: string) => {
    const title = renameDraft.trim();
    setRenamingId(null);
    if (!title) return;
    // Optimista: el título ya se ve mientras viaja la petición
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, title } : c)),
    );
    try {
      await renameConversation(id, title);
    } catch {
      loadConversations();
    }
  };

  const handleDelete = async (id: string) => {
    setConfirmDelete(null);
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (id === activeId) startNewConversation();
    try {
      await deleteConversation(id);
    } catch {
      loadConversations();
    }
  };

  const ask = async (text: string, forceDocId?: string) => {
    const q = text.trim();
    if (!q || sending || !canAsk) return;

    turnSeq.current += 1;
    const id = `turn-${turnSeq.current}`;
    setTurns((prev) => [...prev, { id, question: q, loading: true }]);
    setQuestion("");
    setSending(true);

    // Las sugerencias acotan la búsqueda a su propio documento
    const scope = forceDocId || docFilter;
    try {
      const { data } = await askChat(q, scope ? [scope] : undefined, activeId);
      setTurns((prev) =>
        prev.map((t) => (t.id === id ? { ...t, answer: data, loading: false } : t)),
      );
      // La primera pregunta abre un hilo; hay que adoptarlo para que la
      // siguiente continúe en él y no cree otro.
      if (data.conversation_id && data.conversation_id !== activeId) {
        setActiveId(data.conversation_id);
      }
      loadConversations();
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

  const grouped = groupByRecency(conversations);

  return (
    <div className="mx-auto flex h-[calc(100vh-9rem)] max-w-6xl gap-4">
      {/* ── Panel de conversaciones ──────────────────────────────────────── */}
      {panelOpen && (
        <aside className="card hidden w-64 shrink-0 flex-col overflow-hidden md:flex">
          <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2.5">
            <span className="text-xs font-bold tracking-[0.08em] text-ink-3 uppercase">
              Conversaciones
            </span>
            <button
              onClick={() => setPanelOpen(false)}
              className="btn-icon h-7 w-7"
              aria-label="Ocultar panel de conversaciones"
              title="Ocultar panel"
            >
              <PanelLeftClose className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="p-2">
            <button
              onClick={startNewConversation}
              className={`btn btn-sm w-full ${
                activeId === null ? "btn-soft" : "btn-secondary"
              }`}
            >
              <Plus className="h-3.5 w-3.5" />
              Nueva conversación
            </button>
          </div>

          <div className="flex-1 space-y-3 overflow-y-auto px-2 pb-2">
            {conversations.length === 0 ? (
              <p className="px-2 py-6 text-center text-xs text-ink-3">
                Aún no tienes conversaciones. Haz una pregunta para empezar.
              </p>
            ) : (
              grouped.map((group) => (
                <div key={group.label}>
                  <p className="mb-1 px-2 text-[10px] font-bold tracking-[0.1em] text-ink-3 uppercase">
                    {group.label}
                  </p>
                  <ul className="space-y-0.5">
                    {group.items.map((c) => (
                      <li key={c.id}>
                        {renamingId === c.id ? (
                          <div className="flex items-center gap-1 px-1">
                            <input
                              value={renameDraft}
                              onChange={(e) => setRenameDraft(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") handleRename(c.id);
                                if (e.key === "Escape") setRenamingId(null);
                              }}
                              autoFocus
                              aria-label="Nuevo título"
                              className="input px-2 py-1 text-xs"
                            />
                            <button
                              onClick={() => handleRename(c.id)}
                              className="btn-icon h-6 w-6 shrink-0"
                              aria-label="Guardar título"
                            >
                              <Check className="h-3 w-3" />
                            </button>
                          </div>
                        ) : (
                          <div
                            className={`group flex items-center gap-1 rounded-field px-2 py-1.5 transition-colors ${
                              c.id === activeId
                                ? "bg-brand-soft"
                                : "hover:bg-surface-2"
                            }`}
                          >
                            <button
                              onClick={() => openConversation(c)}
                              className="min-w-0 flex-1 text-left"
                              title={c.title}
                            >
                              <span
                                className={`block truncate text-xs font-medium ${
                                  c.id === activeId
                                    ? "text-brand-soft-fg"
                                    : "text-ink"
                                }`}
                              >
                                {c.title}
                              </span>
                              <span className="mt-0.5 flex items-center gap-1 text-[10px] text-ink-3">
                                {c.document_name ? (
                                  <>
                                    <FileText className="h-2.5 w-2.5 shrink-0" />
                                    <span className="truncate">
                                      {docTitle(c.document_name)}
                                    </span>
                                  </>
                                ) : (
                                  <span>Toda la base</span>
                                )}
                                <span aria-hidden>·</span>
                                <span className="tnum shrink-0">
                                  {c.message_count}
                                </span>
                              </span>
                            </button>
                            {/* Acciones: sólo al pasar el cursor o con foco */}
                            <span className="flex shrink-0 items-center opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                              <button
                                onClick={() => {
                                  setRenamingId(c.id);
                                  setRenameDraft(c.title);
                                }}
                                className="btn-icon h-6 w-6"
                                aria-label={`Renombrar ${c.title}`}
                              >
                                <Pencil className="h-3 w-3" />
                              </button>
                              <button
                                onClick={() => setConfirmDelete(c.id)}
                                className="btn-icon h-6 w-6"
                                aria-label={`Eliminar ${c.title}`}
                              >
                                <Trash2 className="h-3 w-3" />
                              </button>
                            </span>
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ))
            )}
          </div>
        </aside>
      )}

      {/* ── Conversación activa ──────────────────────────────────────────── */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {!panelOpen && (
            <button
              onClick={() => setPanelOpen(true)}
              className="btn-icon hidden md:inline-flex"
              aria-label="Mostrar panel de conversaciones"
              title="Mostrar conversaciones"
            >
              <PanelLeftOpen className="h-4 w-4" />
            </button>
          )}

          <label htmlFor="docFilter" className="text-xs font-medium text-ink-2">
            Buscar en:
          </label>
          <select
            id="docFilter"
            value={docFilter}
            onChange={(e) => setDocFilter(e.target.value)}
            disabled={activeId !== null || !canAsk}
            title={
              activeId !== null
                ? "El alcance queda fijado al abrir la conversación. Empieza una nueva para cambiarlo."
                : undefined
            }
            className="input max-w-xs py-1.5 text-xs"
          >
            <option value="">Todos mis documentos</option>
            {activeScopeMissing && (
              <option value={docFilter}>
                {activeConversation?.document_name ?? "Documento del hilo"}
              </option>
            )}
            {scopeOptions.map((d) => (
              <option key={d.id} value={d.id}>
                {d.filename}
              </option>
            ))}
          </select>

          {activeConversation && (
            <span className="chip chip-neutral">
              <MessageSquare className="h-3 w-3" />
              {activeConversation.message_count} pregunta
              {activeConversation.message_count !== 1 ? "s" : ""}
            </span>
          )}

          <button
            onClick={startNewConversation}
            className="btn btn-secondary btn-sm ml-auto md:hidden"
          >
            <Plus className="h-3.5 w-3.5" />
            Nueva
          </button>
        </div>

        {/* Mensajes */}
        <div className="flex-1 space-y-4 overflow-y-auto pr-1">
          {loadingThread && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-ink-3">
              <Loader2 className="h-4 w-4 animate-spin" />
              Cargando conversación...
            </div>
          )}

          {!loadingThread && turns.length === 0 && (
            <div className="flex h-full flex-col items-center justify-center px-4 text-center">
              <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-soft">
                <MessageSquare className="h-7 w-7 text-brand-soft-fg" />
              </div>
              <p className="font-medium text-ink">Pregunta sobre tus documentos</p>
              <p className="mt-1 max-w-md text-sm text-ink-2">
                Las respuestas se basan únicamente en el contenido disponible, y
                siempre citan el documento y fragmento de origen.
              </p>

              {/* Cuando el chat está bloqueado, el aviso de encima de la
                  entrada ya explica por qué y lleva a Documentos: repetir el
                  mismo texto aquí sólo añadiría ruido. */}
              {block || suggestions.length === 0 ? null : (
                <>
                  <p className="mt-5 flex items-center gap-1.5 text-xs text-ink-3">
                    {faqSuggestions && faqSuggestions.length > 0 ? (
                      <>
                        <HelpCircle className="h-3.5 w-3.5" />
                        Preguntas frecuentes de tus documentos:
                      </>
                    ) : (
                      "Prueba con una de estas preguntas:"
                    )}
                  </p>
                  <div className="mt-2 flex w-full max-w-lg flex-col gap-2">
                    {suggestions.map((s, i) => (
                      <button
                        key={`${s.docId}-${i}`}
                        onClick={() => ask(s.question, s.docId)}
                        className="flex items-start gap-2 rounded-field border border-line bg-surface px-3.5 py-2.5 text-left text-sm text-ink-2 transition-colors hover:border-brand/40 hover:bg-surface-2"
                      >
                        <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand" />
                        <span>
                          {s.question}
                          <span className="mt-0.5 block text-xs text-ink-3">
                            en {s.docLabel}
                          </span>
                        </span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {turns.map((t) => (
            <div key={t.id} className="space-y-2">
              {/* Pregunta */}
              <div className="flex justify-end">
                <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-brand px-4 py-2.5 text-sm text-brand-fg">
                  {t.question}
                </div>
              </div>

              {/* Respuesta */}
              <div className="flex justify-start">
                <div className="w-full max-w-[85%] rounded-2xl rounded-bl-sm border border-line bg-surface px-4 py-3">
                  {t.loading && (
                    <div className="flex items-center gap-2 text-sm text-ink-3">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Buscando en tus documentos...
                    </div>
                  )}

                  {t.error && (
                    <div className="flex items-start gap-2 text-sm text-danger-fg">
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                      {t.error}
                    </div>
                  )}

                  {t.answer && (
                    <>
                      <p className="text-sm leading-relaxed whitespace-pre-wrap text-ink">
                        {t.answer.answer}
                      </p>

                      {t.answer.has_context ? (
                        <div className="mt-2.5 flex flex-wrap items-center gap-3">
                          <ConfidenceChip
                            confidence={t.answer.confidence}
                            available={t.answer.confidence_available}
                          />
                          {t.answer.model && (
                            <span className="text-xs text-ink-3">
                              {t.answer.model}
                            </span>
                          )}
                        </div>
                      ) : (
                        typeof t.answer.searched_documents === "number" && (
                          <p className="mt-2 text-xs text-ink-3">
                            {t.answer.searched_documents > 0
                              ? `Se buscó en ${t.answer.searched_documents} documento${
                                  t.answer.searched_documents !== 1 ? "s" : ""
                                } sin encontrar información relacionada.`
                              : "No hay documentos disponibles para consultar."}
                          </p>
                        )
                      )}

                      {/* Fuentes desplegables */}
                      {t.answer.sources.length > 0 && (
                        <div className="mt-3">
                          <button
                            onClick={() =>
                              setExpanded((p) => ({ ...p, [t.id]: !p[t.id] }))
                            }
                            className="flex items-center gap-1.5 text-xs font-semibold text-brand hover:text-brand-hover"
                          >
                            <FileText className="h-3.5 w-3.5" />
                            {expanded[t.id] ? "Ocultar" : "Ver"} fuentes (
                            {t.answer.sources.length})
                            {expanded[t.id] ? (
                              <ChevronUp className="h-3 w-3" />
                            ) : (
                              <ChevronDown className="h-3 w-3" />
                            )}
                          </button>

                          {expanded[t.id] && (
                            <div className="mt-2 space-y-2">
                              {t.answer.sources.map((s, i) => (
                                <div
                                  key={`${s.doc_id}-${s.chunk_index}-${i}`}
                                  className="rounded-field border border-line bg-surface-2 p-3"
                                >
                                  <div className="mb-1 flex items-center justify-between gap-2">
                                    <span className="truncate text-xs font-medium text-ink-2">
                                      {s.doc_name} · fragmento {s.chunk_index}
                                    </span>
                                    <span className="tnum shrink-0 text-xs text-ink-3">
                                      {Math.round(s.similarity * 100)}% afinidad
                                    </span>
                                  </div>
                                  <p className="text-xs leading-relaxed text-ink-2">
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
        {block && (
          <div className="note note-warning mt-4" role="status">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span className="min-w-0">
              <span className="font-semibold">{BLOCK_COPY[block].title}.</span>{" "}
              {BLOCK_COPY[block].body}
            </span>
            <button
              onClick={() => navigate("/docs")}
              className="btn btn-sm btn-secondary ml-auto shrink-0"
            >
              {BLOCK_COPY[block].cta}
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        <form
          onSubmit={onSubmit}
          data-tour="chat-input"
          className="mt-4 flex items-center gap-2"
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={
              block
                ? "Necesitas un documento analizado para preguntar"
                : activeConversation
                  ? `Seguir en «${activeConversation.title.slice(0, 30)}»...`
                  : "Escribe tu pregunta..."
            }
            disabled={sending || !canAsk}
            aria-label="Pregunta"
            className="input flex-1 rounded-full px-4 py-2.5"
          />
          <button
            type="submit"
            disabled={!question.trim() || sending || !canAsk}
            className="btn btn-primary h-11 w-11 shrink-0 rounded-full p-0"
            aria-label="Enviar pregunta"
          >
            {sending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </button>
        </form>
        {turns.length > 0 && activeConversation && (
          <p className="mt-1.5 text-center text-[11px] text-ink-3">
            Última actividad: {fmtDateTime(activeConversation.updated_at)}
          </p>
        )}
      </div>

      <ConfirmDialog
        open={confirmDelete !== null}
        title="¿Eliminar esta conversación?"
        description="Se borrarán todas sus preguntas y respuestas. Esta acción no se puede deshacer."
        itemName={conversations.find((c) => c.id === confirmDelete)?.title}
        onConfirm={() => confirmDelete && handleDelete(confirmDelete)}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}
