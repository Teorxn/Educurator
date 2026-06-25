import { useEffect, useState, useRef, useCallback } from "react";
import type { DragEvent, ChangeEvent } from "react";
import {
  Upload as UploadIcon,
  BookOpen,
  File,
  X,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Trash2,
  RefreshCw,
} from "lucide-react";
import {
  getReferenceDocs,
  uploadReferenceDoc,
  deleteReferenceDoc,
  processReferenceDocs,
} from "../api/reference-docs";
import type { ReferenceDoc } from "../api/reference-docs";

// ── Helpers ──────────────────────────────────────────────────────────────────

const STATUS_MAP: Record<
  string,
  { bg: string; text: string; dot: string; label: string }
> = {
  needs_review: {
    bg: "bg-gray-100",
    text: "text-gray-700",
    dot: "bg-gray-400",
    label: "Pendiente",
  },
  processing: {
    bg: "bg-yellow-100",
    text: "text-yellow-800",
    dot: "bg-yellow-400 animate-pulse",
    label: "Procesando",
  },
  approved: {
    bg: "bg-green-100",
    text: "text-green-800",
    dot: "bg-green-500",
    label: "Disponible",
  },
  rejected: {
    bg: "bg-red-100",
    text: "text-red-800",
    dot: "bg-red-500",
    label: "Rechazado",
  },
  archived: {
    bg: "bg-blue-100",
    text: "text-blue-800",
    dot: "bg-blue-400",
    label: "Archivado",
  },
};

const FILE_EMOJI: Record<string, string> = { pdf: "📖", docx: "📝", txt: "📃" };

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

// ── Upload section component ─────────────────────────────────────────────────

const ACCEPTED_EXT = [".pdf", ".docx", ".txt"];
const ACCEPTED_MIME = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
];
const MAX_BYTES = 50 * 1024 * 1024;

function validateFile(f: File): string | null {
  const okMime = ACCEPTED_MIME.includes(f.type);
  const okExt = ACCEPTED_EXT.some((ext) => f.name.toLowerCase().endsWith(ext));
  if (!okMime && !okExt) return "Tipo no soportado. Solo PDF, DOCX y TXT.";
  if (f.size > MAX_BYTES) return "El archivo supera el límite de 50 MB.";
  return null;
}

function UploadSection({ onUploaded }: { onUploaded: () => void }) {
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [state, setState] = useState<
    "idle" | "uploading" | "success" | "error"
  >("idle");
  const [progress, setProgress] = useState(0);
  const [errorMsg, setErrorMsg] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback((f: File) => {
    const err = validateFile(f);
    if (err) {
      setErrorMsg(err);
      return;
    }
    setFile(f);
    setState("idle");
    setErrorMsg("");
  }, []);

  const handleUpload = async () => {
    if (!file) return;
    setState("uploading");
    setProgress(0);
    try {
      await uploadReferenceDoc(file, setProgress);
      setProgress(100);
      setState("success");
      onUploaded();
    } catch {
      setState("error");
      setErrorMsg("No se pudo subir el archivo. Intenta nuevamente.");
    }
  };

  const reset = () => {
    setFile(null);
    setState("idle");
    setProgress(0);
    setErrorMsg("");
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
        <UploadIcon className="w-4 h-4 text-violet-500" />
        Subir documento de referencia
      </h3>

      {/* Drop zone */}
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
          border-2 border-dashed rounded-xl p-6 text-center transition-all
          ${!file ? "cursor-pointer" : ""}
          ${dragging ? "border-violet-500 bg-violet-50" : "border-gray-200 hover:border-violet-300 hover:bg-gray-50"}
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
            <div className="w-12 h-12 bg-violet-50 rounded-xl flex items-center justify-center mx-auto mb-3">
              <BookOpen className="w-6 h-6 text-violet-500" />
            </div>
            <p className="text-gray-700 font-medium text-sm mb-1">
              {dragging
                ? "Suelta el archivo aquí"
                : "Arrastra o selecciona un documento"}
            </p>
            <p className="text-xs text-gray-400">
              PDF, DOCX o TXT · máx. 50 MB
            </p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2">
            <div className="w-10 h-10 bg-blue-50 rounded-lg flex items-center justify-center">
              <File className="w-5 h-5 text-blue-500" />
            </div>
            <p className="font-medium text-gray-800 text-sm">{file.name}</p>
            <p className="text-xs text-gray-400">{fmtSize(file.size)}</p>
            {state === "idle" && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  reset();
                }}
                className="text-gray-400 hover:text-gray-600"
                title="Quitar archivo"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
        )}
      </div>

      {/* Messages */}
      {errorMsg && state !== "error" && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3 mt-3">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {errorMsg}
        </div>
      )}

      {state === "uploading" && (
        <div className="mt-3">
          <div className="flex justify-between text-xs text-gray-500 mb-1.5">
            <span>Subiendo...</span>
            <span>{progress}%</span>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
            <div
              className="bg-violet-600 h-2 rounded-full transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {state === "success" && (
        <div className="flex items-center gap-2 bg-green-50 border border-green-200 text-green-800 text-sm rounded-xl px-4 py-3 mt-3">
          <CheckCircle2 className="w-4 h-4 shrink-0 text-green-600" />
          <span>¡Documento de referencia subido!</span>
          <button
            onClick={reset}
            className="ml-auto text-green-700 hover:underline font-medium shrink-0"
          >
            Subir otro
          </button>
        </div>
      )}

      {state === "error" && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3 mt-3">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {errorMsg}
          <button
            onClick={reset}
            className="ml-auto text-red-700 hover:underline font-medium shrink-0"
          >
            Intentar de nuevo
          </button>
        </div>
      )}

      {file && state === "idle" && (
        <button
          onClick={handleUpload}
          className="w-full mt-3 bg-violet-600 hover:bg-violet-700 text-white font-medium py-2 px-4 rounded-xl transition-colors flex items-center justify-center gap-2 text-sm"
        >
          <UploadIcon className="w-4 h-4" />
          Subir como referencia
        </button>
      )}
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function ReferenceDocs() {
  const [docs, setDocs] = useState<ReferenceDoc[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const LIMIT = 20;

  const fetchDocs = async (isFirstLoad = false, currentPage = page) => {
    try {
      const { data } = await getReferenceDocs({
        page: currentPage,
        limit: LIMIT,
      });
      const sorted = [...data.items].sort(
        (a, b) =>
          new Date(b.uploaded_at).getTime() - new Date(a.uploaded_at).getTime(),
      );
      setDocs(sorted);
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
  };

  const goToPage = (newPage: number) => {
    setPage(newPage);
    setLoading(true);
    fetchDocs(true, newPage);
  };

  useEffect(() => {
    fetchDocs(true);
    pollingRef.current = setInterval(() => fetchDocs(false), 5000);
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  const handleDelete = async (id: string) => {
    setDeleting(id);
    try {
      await deleteReferenceDoc(id);
      setDocs((prev) => prev.filter((d) => d.id !== id));
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

  const isPending = docs.some(
    (d) => d.status === "needs_review" || d.status === "processing",
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400 gap-2">
        <RefreshCw className="w-5 h-5 animate-spin" />
        <span className="text-sm">Cargando documentos de referencia...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Upload section */}
      <UploadSection onUploaded={() => fetchDocs(false)} />

      {/* List section */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <BookOpen className="w-4 h-4 text-violet-500" />
            <h2 className="text-sm font-semibold text-gray-700">
              Documentos de referencia
            </h2>
            <span className="text-xs text-gray-400">({docs.length})</span>
          </div>
          <div className="flex items-center gap-2">
            {isPending && (
              <span className="flex items-center gap-1.5 text-xs text-yellow-800 bg-yellow-50 border border-yellow-200 rounded-full px-3 py-1">
                <RefreshCw className="w-3 h-3 animate-spin" />
                Pendiente de procesamiento
              </span>
            )}
            <button
              onClick={handleProcess}
              disabled={processing}
              className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-violet-600 text-white hover:bg-violet-700 disabled:bg-violet-300 transition-colors"
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

        {docs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-14 h-14 bg-gray-100 rounded-2xl flex items-center justify-center mb-4">
              <BookOpen className="w-7 h-7 text-gray-400" />
            </div>
            <p className="text-gray-600 font-medium">
              No hay documentos de referencia
            </p>
            <p className="text-sm text-gray-400 mt-1">
              Sube reglamentos, normativas, FAQs o libros de texto como
              referencia
            </p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Documento
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Tipo
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Estado
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Tamaño
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  Subido
                </th>
                <th className="px-4 py-3 text-right font-medium text-gray-600">
                  Acción
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {docs.map((doc) => {
                const s = STATUS_MAP[doc.status] ?? STATUS_MAP.needs_review;
                return (
                  <tr
                    key={doc.id}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="text-base">
                          {FILE_EMOJI[doc.file_type] ?? "📖"}
                        </span>
                        <span className="font-medium text-gray-800 truncate max-w-xs">
                          {doc.filename}
                        </span>
                        {/* Reference badge */}
                        <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-800">
                          📖 Referencia
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="uppercase text-xs font-semibold text-gray-400 tracking-wide">
                        {doc.file_type}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${s.bg} ${s.text}`}
                      >
                        <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
                        {s.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {fmtSize(doc.size_bytes)}
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {fmtDate(doc.uploaded_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {confirmDelete === doc.id ? (
                        <div className="flex items-center justify-end gap-1.5">
                          <span className="text-xs text-gray-500">
                            ¿Eliminar?
                          </span>
                          <button
                            onClick={() => handleDelete(doc.id)}
                            disabled={deleting === doc.id}
                            className="text-xs font-medium px-2 py-1 rounded bg-red-100 text-red-700 hover:bg-red-200 transition-colors"
                          >
                            {deleting === doc.id ? (
                              <Loader2 className="w-3 h-3 animate-spin" />
                            ) : (
                              "Sí"
                            )}
                          </button>
                          <button
                            onClick={() => setConfirmDelete(null)}
                            className="text-xs font-medium px-2 py-1 rounded bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors"
                          >
                            No
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setConfirmDelete(doc.id)}
                          className="p-1.5 rounded-md text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                          title="Eliminar referencia"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        {/* Pagination */}
        {total > LIMIT && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-gray-100">
            <p className="text-xs text-gray-400">
              {Math.min((page - 1) * LIMIT + 1, total)}–
              {Math.min(page * LIMIT, total)} de {total}
            </p>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => goToPage(page - 1)}
                disabled={page <= 1}
                className="px-2.5 py-1 text-xs font-medium rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Anterior
              </button>
              <button
                onClick={() => goToPage(page + 1)}
                disabled={page * LIMIT >= total}
                className="px-2.5 py-1 text-xs font-medium rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Siguiente
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
