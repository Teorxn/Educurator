import { useCallback, useEffect, useRef, useState } from "react";
import type { DragEvent, ChangeEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Upload as UploadIcon,
  File as FileIcon,
  FileText,
  BookOpen,
  X,
  CheckCircle2,
  AlertCircle,
  Loader2,
  ArrowRight,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Sparkles,
  FlaskConical,
  Trash2,
} from "lucide-react";
import DocBadge from "../components/DocBadge";
import ConfirmDialog from "../components/ConfirmDialog";
import Tabs from "../components/Tabs";
import type { TabItem } from "../components/Tabs";
import { SkeletonTable, LoadingLabel } from "../components/Skeleton";
import { keepIfSame } from "../lib/sameData";
import {
  getDocs,
  getDocsStatus,
  retryDocAnalysis,
  uploadDocsBatch,
  deleteDoc,
} from "../api/docs";
import type { Document, DocStatusEntry } from "../api/docs";
import { triggerCuration } from "../api/analysis";
import { useProfile } from "../useProfile";
import {
  getReferenceDocs,
  uploadReferenceDoc,
  deleteReferenceDoc,
  processReferenceDocs,
} from "../api/reference-docs";
import type { ReferenceDoc } from "../api/reference-docs";

function fmtDate(d: string) {
  return new Intl.DateTimeFormat("es", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(d));
}

function fmtSize(b: number) {
  if (b < 1024) return `${b} B`;
  if (b < 1048576) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1048576).toFixed(1)} MB`;
}

type DocsTab = "curated" | "reference";

/**
 * Módulo único de documentos, con dos pestañas (cada una con su propia
 * subida + listado): antes eran tres secciones separadas del sidebar
 * (Subir documento, Documentos, Documentos de referencia).
 */
export default function Documents() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTab: DocsTab =
    searchParams.get("tab") === "reference" ? "reference" : "curated";
  const [tab, setTab] = useState<DocsTab>(initialTab);

  const switchTab = (next: DocsTab) => {
    setTab(next);
    setSearchParams(next === "reference" ? { tab: "reference" } : {}, {
      replace: true,
    });
  };

  const TABS: TabItem<DocsTab>[] = [
    { id: "curated", icon: FileText, label: "Documentos" },
    {
      id: "reference",
      icon: BookOpen,
      label: "De referencia",
      tour: "tab-reference",
    },
  ];

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <Tabs
        items={TABS}
        value={tab}
        onChange={switchTab}
        label="Tipo de documento"
      />

      {tab === "curated" ? <CuratedDocsPanel /> : <ReferenceDocsPanel />}
    </div>
  );
}

// ── Pestaña "Documentos" (curados) ────────────────────────────────────────────

const ACCEPTED_EXT = [".pdf", ".docx", ".txt"];
const ACCEPTED_MIME = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
];
const MAX_BYTES = 50 * 1024 * 1024;
const MAX_FILES = 10;

interface FileEntry {
  file: File;
  error?: string;
  docId?: string;
  serverError?: string;
}

const AUTO_REDIRECT_KEY = "educurator_auto_redirect";

function validateFile(f: File): string | undefined {
  const okMime = ACCEPTED_MIME.includes(f.type);
  const okExt = ACCEPTED_EXT.some((ext) => f.name.toLowerCase().endsWith(ext));
  if (!okMime && !okExt) return "Tipo no soportado (solo PDF, DOCX o TXT)";
  if (f.size > MAX_BYTES) return "Supera el límite de 50 MB";
  return undefined;
}

function CuratedDocsPanel() {
  const navigate = useNavigate();

  // ── Listado ────────────────────────────────────────────────────────────
  const [docs, setDocs] = useState<Document[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisMsg, setAnalysisMsg] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const { isAdmin } = useProfile();
  const listPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadDocs = useCallback(async (isFirstLoad = false) => {
    try {
      const { data } = await getDocs();
      const sorted = [...data.items].sort(
        (a, b) => new Date(b.uploaded_at).getTime() - new Date(a.uploaded_at).getTime(),
      );
      // Sondeo cada 5 s: si el servidor devuelve lo mismo, no se toca el estado
      // y la tabla no se vuelve a renderizar.
      setDocs((prev) => keepIfSame(prev, sorted));
      const stillWorking = data.items.some(
        (d) => d.status === "processing" || d.status === "queued",
      );
      if (!stillWorking && listPollRef.current) {
        clearInterval(listPollRef.current);
        listPollRef.current = null;
      }
    } catch {
      // silencioso: reintenta en el siguiente tick
    } finally {
      if (isFirstLoad) setDocsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDocs(true);
    listPollRef.current = setInterval(() => loadDocs(false), 5000);
    return () => {
      if (listPollRef.current) clearInterval(listPollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const ensurePolling = () => {
    if (!listPollRef.current) {
      listPollRef.current = setInterval(() => loadDocs(false), 5000);
    }
  };

  const handleDeleteDoc = async (id: string) => {
    setDeletingId(id);
    try {
      await deleteDoc(id);
      setDocs((prev) => prev.filter((d) => d.id !== id));
    } catch {
      // silent
    } finally {
      setDeletingId(null);
      setConfirmDelete(null);
    }
  };

  const handleAnalyzeAll = async () => {
    setAnalyzing(true);
    setAnalysisMsg(null);
    try {
      const { data } = await triggerCuration();
      setAnalysisMsg(
        data.status === "accepted"
          ? "Análisis iniciado. Procesando documentos..."
          : "Error al iniciar el análisis",
      );
      ensurePolling();
    } catch {
      setAnalysisMsg("Error al conectar con el servidor");
    } finally {
      setAnalyzing(false);
      setTimeout(() => setAnalysisMsg(null), 5000);
    }
  };

  // ── Subida ─────────────────────────────────────────────────────────────
  const [uploadOpen, setUploadOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [uploadState, setUploadState] = useState<"idle" | "uploading" | "done">("idle");
  const [progress, setProgress] = useState(0);
  const [notice, setNotice] = useState("");
  const [statuses, setStatuses] = useState<Record<string, DocStatusEntry>>({});
  const [autoRedirect, setAutoRedirect] = useState(
    () => localStorage.getItem(AUTO_REDIRECT_KEY) !== "0",
  );
  const inputRef = useRef<HTMLInputElement>(null);
  const uploadPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const redirectedRef = useRef(false);

  const trackedIds = entries.map((e) => e.docId).filter((id): id is string => Boolean(id));

  useEffect(() => {
    if (trackedIds.length === 0) return;

    const tick = async () => {
      try {
        const { data } = await getDocsStatus();
        const map: Record<string, DocStatusEntry> = {};
        data.items.forEach((it) => {
          if (trackedIds.includes(it.id)) map[it.id] = it;
        });
        setStatuses((prev) => keepIfSame(prev, map));
        // Mantiene la tabla de abajo sincronizada con lo que se sube aquí
        loadDocs(false);

        const tracked = Object.values(map);
        const allFinal =
          tracked.length === trackedIds.length &&
          tracked.every((t) => t.status !== "queued" && t.status !== "processing");

        if (allFinal && uploadPollRef.current) {
          clearInterval(uploadPollRef.current);
          uploadPollRef.current = null;
        }

        if (autoRedirect && !redirectedRef.current) {
          const finished = tracked.find((t) => t.status === "analyzed");
          if (finished) {
            redirectedRef.current = true;
            navigate(`/review?document_id=${finished.id}`);
          }
        }
      } catch {
        // silencioso: reintenta en el siguiente tick
      }
    };

    tick();
    uploadPollRef.current = setInterval(tick, 3000);
    return () => {
      if (uploadPollRef.current) clearInterval(uploadPollRef.current);
      uploadPollRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trackedIds.join(","), autoRedirect]);

  const addFiles = useCallback((files: FileList | File[]) => {
    setNotice("");
    setEntries((prev) => {
      const room = MAX_FILES - prev.length;
      if (room <= 0) {
        setNotice(`Máximo ${MAX_FILES} documentos por carga`);
        return prev;
      }
      const incoming = Array.from(files).slice(0, room);
      if (Array.from(files).length > room) {
        setNotice(`Solo se agregaron ${room}: el máximo es ${MAX_FILES}`);
      }
      const next = incoming.map((file) => ({ file, error: validateFile(file) }));
      return [...prev, ...next];
    });
  }, []);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
  };

  const onInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) addFiles(e.target.files);
  };

  const removeEntry = (idx: number) => setEntries((prev) => prev.filter((_, i) => i !== idx));

  const handleUpload = async () => {
    const valid = entries.filter((e) => !e.error);
    if (valid.length === 0) return;

    setUploadState("uploading");
    setProgress(0);
    redirectedRef.current = false;

    try {
      const { data } = await uploadDocsBatch(
        valid.map((e) => e.file),
        setProgress,
      );

      setEntries((prev) =>
        prev.map((entry) => {
          if (entry.error) return entry;
          const ok = data.uploaded.find(
            (d) => d.original_filename === entry.file.name || d.filename === entry.file.name,
          );
          if (ok) return { ...entry, docId: ok.id, serverError: undefined };
          const bad = data.failed.find((f) => f.filename === entry.file.name);
          if (bad) return { ...entry, serverError: bad.error };
          return entry;
        }),
      );

      setUploadState("done");
      setNotice(`${data.total_queued} de ${data.total_received} documento(s) en cola de análisis`);
      ensurePolling();
      loadDocs(false);
    } catch {
      setUploadState("idle");
      setNotice("No se pudieron subir los archivos. Intenta nuevamente.");
    }
  };

  const resetUpload = () => {
    setEntries([]);
    setStatuses({});
    setUploadState("idle");
    setProgress(0);
    setNotice("");
    redirectedRef.current = false;
    if (inputRef.current) inputRef.current.value = "";
  };

  const toggleAutoRedirect = () => {
    const next = !autoRedirect;
    setAutoRedirect(next);
    localStorage.setItem(AUTO_REDIRECT_KEY, next ? "1" : "0");
  };

  const handleRetry = async (docId: string) => {
    try {
      await retryDocAnalysis(docId);
      redirectedRef.current = false;
      setStatuses((prev) => ({
        ...prev,
        [docId]: { ...prev[docId], status: "queued", error_message: null },
      }));
      ensurePolling();
      loadDocs(false);
    } catch {
      setNotice("No se pudo reintentar el análisis.");
    }
  };

  const validCount = entries.filter((e) => !e.error).length;
  const isPolling = docs.some((d) => d.status === "processing" || d.status === "queued");

  return (
    <div className="space-y-4">
      {/* Panel de subida, colapsable */}
      <div className="card overflow-hidden">
        <button
          onClick={() => setUploadOpen((v) => !v)}
          data-tour="upload-docs"
          className="w-full flex items-center justify-between px-4 py-3 hover:bg-surface-2 transition-colors"
        >
          <span className="flex items-center gap-2 text-sm font-medium text-ink">
            <UploadIcon className="w-4 h-4 text-brand" />
            Subir documentos
          </span>
          {uploadOpen ? (
            <ChevronUp className="w-4 h-4 text-ink-3" />
          ) : (
            <ChevronDown className="w-4 h-4 text-ink-3" />
          )}
        </button>

        {uploadOpen && (
          <div className="px-4 pb-4 pt-1 border-t border-line space-y-3">
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => uploadState !== "uploading" && inputRef.current?.click()}
              className={`border-2 border-dashed rounded-2xl p-8 text-center transition-all cursor-pointer ${
                dragging
                  ? "border-brand bg-brand-soft"
                  : "border-line hover:border-brand/40 hover:bg-surface-2"
              }`}
            >
              <input
                ref={inputRef}
                type="file"
                multiple
                accept={ACCEPTED_EXT.join(",")}
                onChange={onInputChange}
                className="hidden"
              />
              <div className="w-12 h-12 bg-brand-soft rounded-2xl flex items-center justify-center mx-auto mb-3">
                <UploadIcon className="w-6 h-6 text-brand" />
              </div>
              <p className="text-ink font-medium mb-1 text-sm">
                {dragging
                  ? "Suelta los archivos aquí"
                  : "Arrastra uno o varios archivos, o haz clic para seleccionar"}
              </p>
              <p className="text-xs text-ink-3">
                PDF, DOCX o TXT · máx. 50 MB c/u · hasta {MAX_FILES} documentos
              </p>
            </div>

            {notice && (
              <div className="note note-brand">
                <AlertCircle className="w-4 h-4 shrink-0" />
                {notice}
              </div>
            )}

            {entries.length > 0 && (
              <div className="bg-surface-2 rounded-xl border border-line divide-y divide-line">
                {entries.map((entry, idx) => {
                  const st = entry.docId ? statuses[entry.docId] : undefined;

                  return (
                    <div key={`${entry.file.name}-${idx}`} className="p-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2.5 min-w-0">
                          <FileIcon className="w-4 h-4 text-ink-3 shrink-0" />
                          <div className="min-w-0">
                            <p className="text-sm text-ink truncate">{entry.file.name}</p>
                            <p className="text-xs text-ink-3">{fmtSize(entry.file.size)}</p>
                          </div>
                        </div>

                        <div className="flex items-center gap-2 shrink-0">
                          {entry.error && (
                            <span className="chip chip-danger">{entry.error}</span>
                          )}
                          {entry.serverError && (
                            <span className="chip chip-danger">
                              {entry.serverError}
                            </span>
                          )}
                          {st && <DocBadge status={st.status} />}
                          {uploadState === "idle" && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                removeEntry(idx);
                              }}
                              className="text-ink-3 hover:text-ink-2"
                              aria-label="Quitar archivo"
                            >
                              <X className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </div>

                      {uploadState === "uploading" && !entry.error && (
                        <div className="w-full bg-surface-2 rounded-full h-1.5 mt-2 overflow-hidden">
                          <div
                            className="bg-brand h-1.5 rounded-full transition-all duration-300"
                            style={{ width: `${progress}%` }}
                          />
                        </div>
                      )}

                      {st?.status === "error" && (
                        <div className="flex items-center justify-between gap-2 mt-2 text-xs text-danger-fg bg-danger-soft rounded-lg px-3 py-2">
                          <span className="min-w-0 truncate">
                            {st.error_message || "El análisis falló"}
                          </span>
                          <button
                            onClick={() => entry.docId && handleRetry(entry.docId)}
                            className="flex items-center gap-1 font-medium text-danger-fg hover:text-danger-fg shrink-0"
                          >
                            <RefreshCw className="w-3 h-3" />
                            Reintentar
                          </button>
                        </div>
                      )}

                      {st?.status === "analyzed" && (
                        <button
                          onClick={() => navigate(`/review?document_id=${entry.docId}`)}
                          className="flex items-center gap-1 mt-2 text-xs font-medium text-brand hover:text-brand-hover"
                        >
                          Ir a revisión ({st.suggestions_count} sugerencia
                          {st.suggestions_count !== 1 ? "s" : ""})
                          <ArrowRight className="w-3 h-3" />
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            <div className="flex items-center justify-between gap-3 flex-wrap">
              <label className="flex items-center gap-2 text-xs text-ink-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={autoRedirect}
                  onChange={toggleAutoRedirect}
                  className="rounded border-line-strong text-brand focus:ring-brand"
                />
                Ir automáticamente a revisión al terminar el análisis
              </label>

              <div className="flex items-center gap-2">
                {entries.length > 0 && uploadState !== "uploading" && (
                  <button
                    onClick={resetUpload}
                    className="text-sm text-ink-2 hover:text-ink px-3 py-2"
                  >
                    Limpiar
                  </button>
                )}
                {uploadState !== "done" && (
                  <button
                    onClick={handleUpload}
                    disabled={validCount === 0 || uploadState === "uploading"}
                    className="btn btn-primary"
                  >
                    {uploadState === "uploading" ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <UploadIcon className="w-4 h-4" />
                    )}
                    {uploadState === "uploading"
                      ? `Subiendo… ${progress}%`
                      : `Subir ${validCount || ""} documento${validCount !== 1 ? "s" : ""}`}
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {analysisMsg && (
        <div className="note note-info">
          <FlaskConical className="w-4 h-4 shrink-0" />
          {analysisMsg}
        </div>
      )}

      {/* Listado */}
      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-4">
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-brand" />
            <h2 className="section-title">Documentos del curso</h2>
            <span className="text-xs text-ink-3">({docs.length})</span>
          </div>
          <div className="flex items-center gap-2">
            {isPolling && (
              <span className="chip chip-warning">
                <RefreshCw className="w-3 h-3 animate-spin" />
                Agente procesando...
              </span>
            )}
            <button
              onClick={handleAnalyzeAll}
              disabled={analyzing || isPolling}
              data-tour="analyze-all"
              className="btn btn-sm btn-soft"
            >
              {analyzing ? (
                <RefreshCw className="w-3 h-3 animate-spin" />
              ) : (
                <Sparkles className="w-3 h-3" />
              )}
              {analyzing ? "Analizando..." : "Analizar todo"}
            </button>
          </div>
        </div>

        {docsLoading ? (
          <>
            <LoadingLabel>Cargando documentos</LoadingLabel>
            <SkeletonTable
              rows={4}
              cols={["w-1/3", "w-12", "w-24", "w-16", "w-28", "w-8"]}
            />
          </>
        ) : docs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-14 h-14 bg-surface-2 rounded-2xl flex items-center justify-center mb-4">
              <FileText className="w-7 h-7 text-ink-3" />
            </div>
            <p className="text-ink-2 font-medium">No hay documentos aún</p>
            <p className="text-sm text-ink-3 mt-1">
              Sube tu primer documento para comenzar
            </p>
            <button
              onClick={() => setUploadOpen(true)}
              className="btn btn-primary mt-4"
            >
              <UploadIcon className="w-3.5 h-3.5" />
              Subir documento
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-2 border-b border-line">
                <tr>
                  <th className="table-head">Documento</th>
                  <th className="table-head">Tipo</th>
                  <th className="table-head">Estado</th>
                  <th className="table-head">Tamaño</th>
                  {isAdmin && <th className="table-head">Subido por</th>}
                  <th className="table-head">Subido</th>
                  <th className="table-head text-right">Acciones</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {docs.map((doc) => (
                  <tr
                    key={doc.id}
                    onClick={() => navigate(`/docs/${doc.id}`)}
                    className="hover:bg-surface-2 transition-colors cursor-pointer"
                  >
                    <td className="table-cell">
                      <div className="flex items-center gap-2">
                        <span className="text-base">
                          {{ pdf: "📄", docx: "📝", txt: "📃" }[doc.file_type] ?? "📄"}
                        </span>
                        <span className="font-medium text-ink truncate max-w-xs">
                          {doc.filename}
                        </span>
                      </div>
                    </td>
                    <td className="table-cell">
                      <span className="uppercase text-xs font-semibold text-ink-3 tracking-wide">
                        {doc.file_type}
                      </span>
                    </td>
                    <td className="table-cell">
                      <DocBadge status={doc.status} />
                    </td>
                    <td className="table-cell tnum">{fmtSize(doc.size_bytes)}</td>
                    {isAdmin && (
                      <td className="table-cell text-xs truncate max-w-[160px]">
                        {doc.uploader_email ?? "—"}
                      </td>
                    )}
                    <td className="table-cell text-xs">{fmtDate(doc.uploaded_at)}</td>
                    <td className="table-cell text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmDelete(doc.id);
                        }}
                        className="btn-icon h-8 w-8 hover:bg-danger-soft hover:text-danger-fg"
                        title="Eliminar documento"
                        aria-label={`Eliminar ${doc.filename}`}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirmDelete !== null}
        title="¿Eliminar este documento?"
        description="Se borrarán también sus fragmentos, sugerencias e historial. Esta acción no se puede deshacer."
        itemName={docs.find((d) => d.id === confirmDelete)?.filename}
        loading={deletingId !== null}
        onConfirm={() => confirmDelete && handleDeleteDoc(confirmDelete)}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}

// ── Pestaña "Documentos de referencia" ────────────────────────────────────────

/* Mismo distintivo de estado que los documentos curados; sólo cambia el
   vocabulario de los estados que significan otra cosa en el corpus. */
const REF_STATUS_LABELS: Record<string, string> = {
  needs_review: "Pendiente",
  approved: "Disponible",
};

const REF_FILE_EMOJI: Record<string, string> = { pdf: "📖", docx: "📝", txt: "📃" };

function validateReferenceFile(f: File): string | null {
  const okMime = ACCEPTED_MIME.includes(f.type);
  const okExt = ACCEPTED_EXT.some((ext) => f.name.toLowerCase().endsWith(ext));
  if (!okMime && !okExt) return "Tipo no soportado. Solo PDF, DOCX y TXT.";
  if (f.size > MAX_BYTES) return "El archivo supera el límite de 50 MB.";
  return null;
}

function ReferenceDocsPanel() {
  const navigate = useNavigate();
  const [docs, setDocs] = useState<ReferenceDoc[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const LIMIT = 20;

  const fetchDocs = useCallback(
    async (isFirstLoad = false, currentPage = page) => {
      try {
        const { data } = await getReferenceDocs({ page: currentPage, limit: LIMIT });
        const sorted = [...data.items].sort(
          (a, b) => new Date(b.uploaded_at).getTime() - new Date(a.uploaded_at).getTime(),
        );
        setDocs((prev) => keepIfSame(prev, sorted));
        setTotal(data.total);

        const hasProcessing = data.items.some(
          (d) => d.status === "processing" || d.status === "needs_review",
        );
        if (!hasProcessing && pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
      } catch {
        // silent
      } finally {
        if (isFirstLoad) setLoading(false);
      }
    },
    [page],
  );

  const ensurePolling = () => {
    if (!pollingRef.current) {
      pollingRef.current = setInterval(() => fetchDocs(false), 5000);
    }
  };

  const goToPage = (newPage: number) => {
    setPage(newPage);
    setLoading(true);
    fetchDocs(true, newPage);
  };

  useEffect(() => {
    const timer = setTimeout(() => fetchDocs(true), 0);
    pollingRef.current = setInterval(() => fetchDocs(false), 5000);
    return () => {
      clearTimeout(timer);
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [fetchDocs]);

  const handleDelete = async (id: string) => {
    setDeleting(id);
    try {
      await deleteReferenceDoc(id);
      setDocs((prev) => prev.filter((d) => d.id !== id));
      setTotal((t) => Math.max(0, t - 1));
    } catch {
      // silent
    } finally {
      setDeleting(null);
      setConfirmDelete(null);
    }
  };

  const handleProcess = async () => {
    setProcessing(true);
    try {
      await processReferenceDocs();
      await fetchDocs(false);
    } catch {
      // silent
    } finally {
      setProcessing(false);
    }
  };

  const isPending = docs.some((d) => d.status === "needs_review" || d.status === "processing");

  // ── Subida (documento único) ──────────────────────────────────────────────
  const [uploadOpen, setUploadOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uploadState, setUploadState] = useState<"idle" | "uploading" | "success" | "error">(
    "idle",
  );
  const [progress, setProgress] = useState(0);
  const [errorMsg, setErrorMsg] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback((f: File) => {
    const err = validateReferenceFile(f);
    if (err) {
      setErrorMsg(err);
      return;
    }
    setFile(f);
    setUploadState("idle");
    setErrorMsg("");
  }, []);

  const handleUpload = async () => {
    if (!file) return;
    setUploadState("uploading");
    setProgress(0);
    try {
      await uploadReferenceDoc(file, setProgress);
      setProgress(100);
      setUploadState("success");
      ensurePolling();
      fetchDocs(false);
    } catch {
      setUploadState("error");
      setErrorMsg("No se pudo subir el archivo. Intenta nuevamente.");
    }
  };

  const resetUpload = () => {
    setFile(null);
    setUploadState("idle");
    setProgress(0);
    setErrorMsg("");
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="space-y-4">
      {/* Panel de subida, colapsable */}
      <div className="card overflow-hidden">
        <button
          onClick={() => setUploadOpen((v) => !v)}
          className="w-full flex items-center justify-between px-4 py-3 hover:bg-surface-2 transition-colors"
        >
          <span className="flex items-center gap-2 text-sm font-medium text-ink">
            <UploadIcon className="w-4 h-4 text-brand" />
            Subir documento de referencia
          </span>
          {uploadOpen ? (
            <ChevronUp className="w-4 h-4 text-ink-3" />
          ) : (
            <ChevronDown className="w-4 h-4 text-ink-3" />
          )}
        </button>

        {uploadOpen && (
          <div className="px-4 pb-4 pt-1 border-t border-line">
            <p className="text-xs text-ink-3 mb-3">
              Reglamentos, normativas, FAQs o libros de texto: corpus compartido por todo el
              equipo docente.
            </p>

            <div
              onDragOver={(e: DragEvent) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e: DragEvent) => {
                e.preventDefault();
                setDragging(false);
                const f = e.dataTransfer.files[0];
                if (f) handleFile(f);
              }}
              onClick={() => !file && inputRef.current?.click()}
              className={`
                border-2 border-dashed rounded-2xl p-8 text-center transition-all
                ${!file ? "cursor-pointer" : ""}
                ${dragging ? "border-brand bg-brand-soft" : "border-line hover:border-brand/40 hover:bg-surface-2"}
              `}
            >
              <input
                ref={inputRef}
                type="file"
                accept={ACCEPTED_EXT.join(",")}
                onChange={(e: ChangeEvent<HTMLInputElement>) => {
                  const f = e.target.files?.[0];
                  if (f) handleFile(f);
                }}
                className="hidden"
              />

              {!file ? (
                <div>
                  <div className="w-12 h-12 bg-brand-soft rounded-2xl flex items-center justify-center mx-auto mb-3">
                    <BookOpen className="w-6 h-6 text-brand" />
                  </div>
                  <p className="text-ink font-medium text-sm mb-1">
                    {dragging ? "Suelta el archivo aquí" : "Arrastra o selecciona un documento"}
                  </p>
                  <p className="text-xs text-ink-3">PDF, DOCX o TXT · máx. 50 MB</p>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2">
                  <div className="w-10 h-10 bg-info-soft rounded-lg flex items-center justify-center">
                    <FileIcon className="w-5 h-5 text-info-fg" />
                  </div>
                  <p className="font-medium text-ink text-sm">{file.name}</p>
                  <p className="text-xs text-ink-3">{fmtSize(file.size)}</p>
                  {uploadState === "idle" && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        resetUpload();
                      }}
                      className="text-ink-3 hover:text-ink-2"
                      title="Quitar archivo"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  )}
                </div>
              )}
            </div>

            {errorMsg && uploadState !== "error" && (
              <div className="note note-danger mt-3">
                <AlertCircle className="w-4 h-4 shrink-0" />
                {errorMsg}
              </div>
            )}

            {uploadState === "uploading" && (
              <div className="mt-3">
                <div className="flex justify-between text-xs text-ink-2 mb-1.5">
                  <span>Subiendo...</span>
                  <span>{progress}%</span>
                </div>
                <div className="w-full bg-surface-2 rounded-full h-2 overflow-hidden">
                  <div
                    className="bg-brand h-2 rounded-full transition-all duration-300"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            )}

            {uploadState === "success" && (
              <div className="note note-success mt-3 items-center">
                <CheckCircle2 className="w-4 h-4 shrink-0 text-success-fg" />
                <span>¡Documento de referencia subido!</span>
                <button
                  onClick={resetUpload}
                  className="ml-auto text-success-fg hover:underline font-medium shrink-0"
                >
                  Subir otro
                </button>
              </div>
            )}

            {uploadState === "error" && (
              <div className="note note-danger mt-3 items-center">
                <AlertCircle className="w-4 h-4 shrink-0" />
                {errorMsg}
                <button
                  onClick={resetUpload}
                  className="ml-auto text-danger-fg hover:underline font-medium shrink-0"
                >
                  Intentar de nuevo
                </button>
              </div>
            )}

            {file && uploadState === "idle" && (
              <button
                onClick={handleUpload}
                className="btn btn-primary mt-3 w-full"
              >
                <UploadIcon className="w-4 h-4" />
                Subir como referencia
              </button>
            )}
          </div>
        )}
      </div>

      {/* Listado */}
      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-4">
          <div className="flex items-center gap-2">
            <BookOpen className="w-4 h-4 text-brand" />
            <h2 className="section-title">Documentos de referencia</h2>
            <span className="text-xs text-ink-3">({docs.length})</span>
          </div>
          <div className="flex items-center gap-2">
            {isPending && (
              <span className="chip chip-warning">
                <RefreshCw className="w-3 h-3 animate-spin" />
                Pendiente de procesamiento
              </span>
            )}
            <button
              onClick={handleProcess}
              disabled={processing}
              className="btn btn-sm btn-soft"
            >
              {processing ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <RefreshCw className="w-3 h-3" />
              )}
              Procesar
            </button>
          </div>
        </div>

        {loading ? (
          <>
            <LoadingLabel>Cargando documentos de referencia</LoadingLabel>
            <SkeletonTable
              rows={4}
              cols={["w-1/3", "w-12", "w-24", "w-16", "w-28", "w-8"]}
            />
          </>
        ) : docs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-14 h-14 bg-surface-2 rounded-2xl flex items-center justify-center mb-4">
              <BookOpen className="w-7 h-7 text-ink-3" />
            </div>
            <p className="text-ink-2 font-medium">No hay documentos de referencia</p>
            <p className="text-sm text-ink-3 mt-1">
              Sube reglamentos, normativas, FAQs o libros de texto como referencia
            </p>
            <button
              onClick={() => setUploadOpen(true)}
              className="btn btn-primary mt-4"
            >
              <UploadIcon className="w-3.5 h-3.5" />
              Subir referencia
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-2 border-b border-line">
                <tr>
                  <th className="table-head">Documento</th>
                  <th className="table-head">Tipo</th>
                  <th className="table-head">Estado</th>
                  <th className="table-head">Tamaño</th>
                  <th className="table-head">Subido</th>
                  <th className="table-head text-right">Acciones</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {docs.map((doc) => (
                  <tr
                    key={doc.id}
                    onClick={() => navigate(`/docs/${doc.id}`)}
                    className="hover:bg-surface-2 transition-colors cursor-pointer"
                  >
                    <td className="table-cell">
                      <div className="flex items-center gap-2">
                        <span className="text-base">
                          {REF_FILE_EMOJI[doc.file_type] ?? "📖"}
                        </span>
                        <span className="font-medium text-ink truncate max-w-xs">
                          {doc.filename}
                        </span>
                        <span className="chip chip-warning">📖 Referencia</span>
                      </div>
                    </td>
                    <td className="table-cell">
                      <span className="uppercase text-xs font-semibold text-ink-3 tracking-wide">
                        {doc.file_type}
                      </span>
                    </td>
                    <td className="table-cell">
                      <DocBadge status={doc.status} labels={REF_STATUS_LABELS} />
                    </td>
                    <td className="table-cell tnum">{fmtSize(doc.size_bytes)}</td>
                    <td className="table-cell text-xs">{fmtDate(doc.uploaded_at)}</td>
                    <td className="table-cell text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmDelete(doc.id);
                        }}
                        className="btn-icon h-8 w-8 hover:bg-danger-soft hover:text-danger-fg"
                        title="Eliminar referencia"
                        aria-label={`Eliminar ${doc.filename}`}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {total > LIMIT && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-line">
            <p className="text-xs text-ink-3">
              {Math.min((page - 1) * LIMIT + 1, total)}–{Math.min(page * LIMIT, total)} de {total}
            </p>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => goToPage(page - 1)}
                disabled={page <= 1}
                className="px-2.5 py-1 text-xs font-medium rounded-lg border border-line text-ink-2 hover:bg-surface-2 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Anterior
              </button>
              <button
                onClick={() => goToPage(page + 1)}
                disabled={page * LIMIT >= total}
                className="px-2.5 py-1 text-xs font-medium rounded-lg border border-line text-ink-2 hover:bg-surface-2 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Siguiente
              </button>
            </div>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirmDelete !== null}
        title="¿Eliminar este documento de referencia?"
        description="Dejará de usarse como criterio del agente y se borrarán sus fragmentos. Esta acción no se puede deshacer."
        itemName={docs.find((d) => d.id === confirmDelete)?.filename}
        loading={deleting !== null}
        onConfirm={() => confirmDelete && handleDelete(confirmDelete)}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}
