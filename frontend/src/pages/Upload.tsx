import { useCallback, useEffect, useRef, useState } from "react";
import type { DragEvent, ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  Upload as UploadIcon,
  File as FileIcon,
  X,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Clock,
  Cpu,
  ArrowRight,
  RefreshCw,
} from "lucide-react";
import {
  getDocsStatus,
  retryDocAnalysis,
  uploadDocsBatch,
} from "../api/docs";
import type { DocStatus, DocStatusEntry } from "../api/docs";

const ACCEPTED_MIME = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
];
const ACCEPTED_EXT = [".pdf", ".docx", ".txt"];
const MAX_BYTES = 50 * 1024 * 1024;
const MAX_FILES = 10;

type UploadState = "idle" | "uploading" | "done";

interface FileEntry {
  file: File;
  /** Error de validación local (no se envía al servidor) */
  error?: string;
  /** Id del documento creado, tras subir con éxito */
  docId?: string;
  /** Error devuelto por el servidor */
  serverError?: string;
}

// HU-23 — presentación de cada estado del procesamiento
const STATUS_UI: Record<
  DocStatus,
  { label: string; color: string; icon: typeof Clock; spin?: boolean }
> = {
  queued: {
    label: "En cola",
    color: "bg-gray-100 text-gray-600 border-gray-200",
    icon: Clock,
  },
  processing: {
    label: "Procesando",
    color: "bg-blue-50 text-blue-700 border-blue-200",
    icon: Cpu,
    spin: true,
  },
  analyzed: {
    label: "Analizado",
    color: "bg-green-50 text-green-700 border-green-200",
    icon: CheckCircle2,
  },
  error: {
    label: "Error",
    color: "bg-red-50 text-red-700 border-red-200",
    icon: AlertCircle,
  },
  needs_review: {
    label: "Por revisar",
    color: "bg-yellow-50 text-yellow-700 border-yellow-200",
    icon: Clock,
  },
  approved: {
    label: "Aprobado",
    color: "bg-green-50 text-green-700 border-green-200",
    icon: CheckCircle2,
  },
  rejected: {
    label: "Rechazado",
    color: "bg-red-50 text-red-700 border-red-200",
    icon: AlertCircle,
  },
  archived: {
    label: "Archivado",
    color: "bg-gray-100 text-gray-500 border-gray-200",
    icon: FileIcon,
  },
};

const AUTO_REDIRECT_KEY = "educurator_auto_redirect";

function validateFile(f: File): string | undefined {
  const okMime = ACCEPTED_MIME.includes(f.type);
  const okExt = ACCEPTED_EXT.some((ext) => f.name.toLowerCase().endsWith(ext));
  if (!okMime && !okExt) return "Tipo no soportado (solo PDF, DOCX o TXT)";
  if (f.size > MAX_BYTES) return "Supera el límite de 50 MB";
  return undefined;
}

function fmtSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * HU-22 — Subir múltiples documentos
 * HU-23 — Consultar el estado del procesamiento
 * HU-24 — Redirección automática a revisión al finalizar
 */
export default function Upload() {
  const navigate = useNavigate();
  const [dragging, setDragging] = useState(false);
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [state, setState] = useState<UploadState>("idle");
  const [progress, setProgress] = useState(0);
  const [notice, setNotice] = useState("");
  const [statuses, setStatuses] = useState<Record<string, DocStatusEntry>>({});
  const [autoRedirect, setAutoRedirect] = useState(
    () => localStorage.getItem(AUTO_REDIRECT_KEY) !== "0",
  );

  const inputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const redirectedRef = useRef(false);

  const trackedIds = entries
    .map((e) => e.docId)
    .filter((id): id is string => Boolean(id));

  // ── HU-23: polling del estado; se detiene al llegar a estado final ──────
  useEffect(() => {
    if (trackedIds.length === 0) return;

    const tick = async () => {
      try {
        const { data } = await getDocsStatus();
        const map: Record<string, DocStatusEntry> = {};
        data.items.forEach((it) => {
          if (trackedIds.includes(it.id)) map[it.id] = it;
        });
        setStatuses(map);

        const tracked = Object.values(map);
        const allFinal =
          tracked.length === trackedIds.length &&
          tracked.every((t) => t.status !== "queued" && t.status !== "processing");

        if (allFinal && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }

        // ── HU-24: redirección automática al primer documento analizado ──
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
    pollRef.current = setInterval(tick, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
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

  const removeEntry = (idx: number) =>
    setEntries((prev) => prev.filter((_, i) => i !== idx));

  const handleUpload = async () => {
    const valid = entries.filter((e) => !e.error);
    if (valid.length === 0) return;

    setState("uploading");
    setProgress(0);
    redirectedRef.current = false;

    try {
      const { data } = await uploadDocsBatch(
        valid.map((e) => e.file),
        setProgress,
      );

      // Asociar cada resultado a su entrada por nombre de archivo
      setEntries((prev) =>
        prev.map((entry) => {
          if (entry.error) return entry;
          const ok = data.uploaded.find(
            (d) =>
              d.original_filename === entry.file.name ||
              d.filename === entry.file.name,
          );
          if (ok) return { ...entry, docId: ok.id, serverError: undefined };
          const bad = data.failed.find((f) => f.filename === entry.file.name);
          if (bad) return { ...entry, serverError: bad.error };
          return entry;
        }),
      );

      setState("done");
      setNotice(
        `${data.total_queued} de ${data.total_received} documento(s) en cola de análisis`,
      );
    } catch {
      setState("idle");
      setNotice("No se pudieron subir los archivos. Intenta nuevamente.");
    }
  };

  const reset = () => {
    setEntries([]);
    setStatuses({});
    setState("idle");
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
    } catch {
      setNotice("No se pudo reintentar el análisis.");
    }
  };

  const validCount = entries.filter((e) => !e.error).length;

  return (
    <div className="max-w-3xl space-y-4">
      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => state !== "uploading" && inputRef.current?.click()}
        className={`border-2 border-dashed rounded-2xl p-10 text-center transition-all cursor-pointer ${
          dragging
            ? "border-violet-500 bg-violet-50"
            : "border-gray-200 bg-white hover:border-violet-300 hover:bg-gray-50"
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
        <div className="w-14 h-14 bg-violet-50 rounded-2xl flex items-center justify-center mx-auto mb-3">
          <UploadIcon className="w-7 h-7 text-violet-500" />
        </div>
        <p className="text-gray-700 font-medium mb-1">
          {dragging
            ? "Suelta los archivos aquí"
            : "Arrastra uno o varios archivos, o haz clic para seleccionar"}
        </p>
        <p className="text-sm text-gray-400">
          PDF, DOCX o TXT · máx. 50 MB c/u · hasta {MAX_FILES} documentos
        </p>
      </div>

      {notice && (
        <div className="flex items-center gap-2 bg-violet-50 border border-violet-200 text-violet-700 text-sm rounded-xl px-4 py-3">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {notice}
        </div>
      )}

      {/* Lista de archivos con estado individual */}
      {entries.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-50">
          {entries.map((entry, idx) => {
            const st = entry.docId ? statuses[entry.docId] : undefined;
            const ui = st ? STATUS_UI[st.status] : undefined;
            const StatusIcon = ui?.icon;

            return (
              <div key={`${entry.file.name}-${idx}`} className="p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <FileIcon className="w-4 h-4 text-gray-400 shrink-0" />
                    <div className="min-w-0">
                      <p className="text-sm text-gray-800 truncate">
                        {entry.file.name}
                      </p>
                      <p className="text-xs text-gray-400">
                        {fmtSize(entry.file.size)}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {entry.error && (
                      <span className="text-xs text-red-600 bg-red-50 border border-red-200 px-2 py-0.5 rounded-full">
                        {entry.error}
                      </span>
                    )}
                    {entry.serverError && (
                      <span className="text-xs text-red-600 bg-red-50 border border-red-200 px-2 py-0.5 rounded-full">
                        {entry.serverError}
                      </span>
                    )}
                    {ui && StatusIcon && (
                      <span
                        className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full border ${ui.color}`}
                      >
                        <StatusIcon
                          className={`w-3 h-3 ${ui.spin ? "animate-spin" : ""}`}
                        />
                        {ui.label}
                      </span>
                    )}
                    {state === "idle" && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          removeEntry(idx);
                        }}
                        className="text-gray-400 hover:text-gray-600"
                        aria-label="Quitar archivo"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                </div>

                {/* Barra de progreso por documento */}
                {state === "uploading" && !entry.error && (
                  <div className="w-full bg-gray-100 rounded-full h-1.5 mt-2 overflow-hidden">
                    <div
                      className="bg-violet-600 h-1.5 rounded-full transition-all duration-300"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                )}

                {/* Error del pipeline + reintento (HU-23) */}
                {st?.status === "error" && (
                  <div className="flex items-center justify-between gap-2 mt-2 text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">
                    <span className="min-w-0 truncate">
                      {st.error_message || "El análisis falló"}
                    </span>
                    <button
                      onClick={() => entry.docId && handleRetry(entry.docId)}
                      className="flex items-center gap-1 font-medium text-red-700 hover:text-red-800 shrink-0"
                    >
                      <RefreshCw className="w-3 h-3" />
                      Reintentar
                    </button>
                  </div>
                )}

                {/* HU-23: acceso directo cuando termina */}
                {st?.status === "analyzed" && (
                  <button
                    onClick={() => navigate(`/review?document_id=${entry.docId}`)}
                    className="flex items-center gap-1 mt-2 text-xs font-medium text-violet-600 hover:text-violet-700"
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

      {/* Acciones */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <label className="flex items-center gap-2 text-xs text-gray-500 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={autoRedirect}
            onChange={toggleAutoRedirect}
            className="rounded border-gray-300 text-violet-600 focus:ring-violet-500"
          />
          Ir automáticamente a revisión al terminar el análisis
        </label>

        <div className="flex items-center gap-2">
          {entries.length > 0 && state !== "uploading" && (
            <button
              onClick={reset}
              className="text-sm text-gray-600 hover:text-gray-800 px-3 py-2"
            >
              Limpiar
            </button>
          )}
          {state !== "done" && (
            <button
              onClick={handleUpload}
              disabled={validCount === 0 || state === "uploading"}
              className="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 disabled:bg-violet-300 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
            >
              {state === "uploading" ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <UploadIcon className="w-4 h-4" />
              )}
              {state === "uploading"
                ? `Subiendo… ${progress}%`
                : `Subir ${validCount || ""} documento${validCount !== 1 ? "s" : ""}`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
