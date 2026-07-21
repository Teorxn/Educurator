import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  FileText,
  RefreshCw,
  Clock,
  HardDrive,
  Hash,
  Layers,
  BookOpen,
  Trash2,
  Download,
  Eye,
  CheckCircle2,
  AlertCircle,
  User as UserIcon,
} from "lucide-react";
import DocBadge from "../components/DocBadge";
import {
  getDoc,
  getDocContent,
  getDocHistory,
  deleteDoc,
  getDocDetail,
  downloadDoc,
  docDownloadUrl,
  patchDocStatus,
} from "../api/docs";
import type {
  Document,
  DocContent,
  HistoryRecord,
  DocumentDetail,
} from "../api/docs";

const FILE_EMOJI: Record<string, string> = { pdf: "📄", docx: "📝", txt: "📃" };

function fmtDate(d: string | null) {
  if (!d) return "—";
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

const ACTION_LABELS: Record<string, string> = {
  approved: "Aprobado",
  rejected: "Rechazado",
  archived: "Archivado",
  needs_review: "Marcado como pendiente",
  processing: "Procesado",
};

export default function DocDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [doc, setDoc] = useState<Document | null>(null);
  const [content, setContent] = useState<DocContent | null>(null);
  const [history, setHistory] = useState<HistoryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // HU-25 — metadatos ampliados y vista previa
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  // HU-27 — aprobación del documento
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState("");
  const [activeTab, setActiveTab] = useState<"content" | "chunks" | "history">(
    "content",
  );

  useEffect(() => {
    if (!id) return;
    let cancelled = false;

    const load = async () => {
      try {
        const [docRes, contentRes, historyRes, detailRes] = await Promise.all([
          getDoc(id),
          getDocContent(id),
          getDocHistory(id, { limit: 50 }),
          getDocDetail(id).catch(() => null),
        ]);
        if (cancelled) return;
        setDoc(docRes.data);
        setContent(contentRes.data);
        setHistory(historyRes.data.items);
        if (detailRes) setDetail(detailRes.data);
      } catch (err: unknown) {
        if (cancelled) return;
        const msg =
          err instanceof Error ? err.message : "Error al cargar el documento";
        if (msg.includes("404")) {
          setError("Documento no encontrado");
        } else {
          setError(msg);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const handleDelete = async () => {
    if (!id) return;
    setDeleting(true);
    try {
      await deleteDoc(id);
      navigate("/docs");
    } catch {
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  // HU-25 — descarga del original (byte a byte idéntico al subido)
  const handleDownload = async () => {
    if (!id || !doc) return;
    try {
      const { data } = await downloadDoc(id);
      const url = URL.createObjectURL(data);
      const a = document.createElement("a");
      a.href = url;
      a.download = content?.original_filename || doc.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      setApproveError("No se pudo descargar el documento.");
    }
  };

  // HU-27 — aprobar solo si todas las sugerencias fueron revisadas
  const handleApproveDoc = async () => {
    if (!id) return;
    setApproving(true);
    setApproveError("");
    try {
      const { data } = await patchDocStatus(id, "approved");
      setDoc(data);
      if (detail) setDetail({ ...detail, status: data.status });
    } catch (e) {
      const detailMsg = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setApproveError(
        detailMsg || "No se pudo aprobar el documento. Intenta de nuevo.",
      );
    } finally {
      setApproving(false);
    }
  };

  const pendingSuggestions = detail?.pending_suggestions ?? 0;
  const canApprove = pendingSuggestions === 0 && doc?.status !== "approved";

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400 gap-2">
        <RefreshCw className="w-5 h-5 animate-spin" />
        <span className="text-sm">Cargando documento...</span>
      </div>
    );
  }

  if (error || !doc) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-center">
        <div className="w-14 h-14 bg-red-50 rounded-2xl flex items-center justify-center mb-4">
          <FileText className="w-7 h-7 text-red-400" />
        </div>
        <p className="text-gray-600 font-medium">
          {error || "No se pudo cargar el documento"}
        </p>
        <button
          onClick={() => navigate("/docs")}
          className="mt-4 flex items-center gap-2 bg-violet-600 hover:bg-violet-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Volver a documentos
        </button>
      </div>
    );
  }

  const chunkCount = content?.chunks.length ?? 0;
  const totalTokens =
    content?.chunks.reduce((acc, c) => acc + c.token_count, 0) ?? 0;

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Back button */}
      <button
        onClick={() => navigate("/docs")}
        className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-violet-600 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Volver a documentos
      </button>

      {/* Header card */}
      <div className="bg-white border border-gray-200 rounded-xl p-5">
        <div className="flex items-start gap-3">
          <span className="text-2xl">{FILE_EMOJI[doc.file_type] ?? "📄"}</span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-lg font-semibold text-gray-900 truncate">
                {doc.filename}
              </h2>
              {doc.category === "reference" && (
                <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-800 shrink-0">
                  📖 Referencia
                </span>
              )}
            </div>
            {content?.original_filename &&
              content.original_filename !== doc.filename && (
                <p className="text-xs text-gray-400 mt-0.5">
                  Original: {content.original_filename}
                </p>
              )}
          </div>
          <DocBadge status={doc.status} />

          {/* HU-25 — vista previa y descarga del original */}
          <div className="flex items-center gap-1 shrink-0">
            {doc.file_type === "pdf" && (
              <button
                onClick={() => setShowPreview((v) => !v)}
                className="p-2 rounded-md text-gray-400 hover:text-violet-600 hover:bg-violet-50 transition-colors"
                title={showPreview ? "Ocultar vista previa" : "Vista previa"}
              >
                <Eye className="w-4 h-4" />
              </button>
            )}
            <button
              onClick={handleDownload}
              className="p-2 rounded-md text-gray-400 hover:text-violet-600 hover:bg-violet-50 transition-colors"
              title="Descargar original"
            >
              <Download className="w-4 h-4" />
            </button>
          </div>

          <div className="shrink-0">
            {confirmDelete ? (
              <div className="flex items-center gap-1.5">
                <button
                  onClick={handleDelete}
                  disabled={deleting}
                  className="text-xs font-medium px-2.5 py-1.5 rounded-md bg-red-600 text-white hover:bg-red-700 transition-colors disabled:opacity-50"
                >
                  {deleting ? "Eliminando..." : "Confirmar"}
                </button>
                <button
                  onClick={() => setConfirmDelete(false)}
                  disabled={deleting}
                  className="text-xs font-medium px-2.5 py-1.5 rounded-md bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors"
                >
                  Cancelar
                </button>
              </div>
            ) : (
              <button
                onClick={() => setConfirmDelete(true)}
                className="p-2 rounded-md text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                title="Eliminar documento"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>

        {/* Metadata grid */}
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
          <div className="flex items-center gap-2 text-gray-500">
            <HardDrive className="w-3.5 h-3.5 shrink-0" />
            <span>{fmtSize(doc.size_bytes)}</span>
          </div>
          <div className="flex items-center gap-2 text-gray-500">
            <Hash className="w-3.5 h-3.5 shrink-0" />
            <span className="uppercase">{doc.file_type}</span>
          </div>
          <div className="flex items-center gap-2 text-gray-500">
            <Clock className="w-3.5 h-3.5 shrink-0" />
            <span>{fmtDate(doc.uploaded_at)}</span>
          </div>
          <div className="flex items-center gap-2 text-gray-500">
            <Layers className="w-3.5 h-3.5 shrink-0" />
            <span>
              {chunkCount} chunk{chunkCount !== 1 ? "s" : ""} ·{" "}
              {totalTokens.toLocaleString()} tokens
            </span>
          </div>
          {/* HU-25 — uploader */}
          {detail?.uploader_email && (
            <div className="flex items-center gap-2 text-gray-500">
              <UserIcon className="w-3.5 h-3.5 shrink-0" />
              <span className="truncate">{detail.uploader_email}</span>
            </div>
          )}
        </div>

        {/* HU-23 — mensaje de error del pipeline */}
        {doc.status === "error" && doc.error_message && (
          <div className="flex items-start gap-2 mt-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            {doc.error_message}
          </div>
        )}

        {/* HU-27 — aprobación del documento */}
        {detail && doc.status !== "approved" && (
          <div className="flex items-center justify-between gap-3 mt-4 pt-3 border-t border-gray-100 flex-wrap">
            <p className="text-xs text-gray-500">
              {pendingSuggestions > 0 ? (
                <>
                  No puedes aprobar este documento:{" "}
                  <strong className="text-yellow-700">
                    {pendingSuggestions} sugerencia
                    {pendingSuggestions !== 1 ? "s" : ""}
                  </strong>{" "}
                  {pendingSuggestions !== 1 ? "están" : "está"} pendiente
                  {pendingSuggestions !== 1 ? "s" : ""} de revisión.{" "}
                  <button
                    onClick={() => navigate(`/review?document_id=${doc.id}`)}
                    className="text-violet-600 hover:text-violet-700 font-medium"
                  >
                    Ir a revisión →
                  </button>
                </>
              ) : (
                <>Todas las sugerencias fueron revisadas.</>
              )}
            </p>
            <button
              onClick={handleApproveDoc}
              disabled={!canApprove || approving}
              title={
                pendingSuggestions > 0
                  ? "Revisa todas las sugerencias antes de aprobar"
                  : "Aprobar documento"
              }
              className="flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed transition-colors"
            >
              <CheckCircle2 className="w-4 h-4" />
              {approving ? "Aprobando..." : "Aprobar documento"}
            </button>
          </div>
        )}

        {approveError && (
          <div className="flex items-start gap-2 mt-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            {approveError}
          </div>
        )}
      </div>

      {/* HU-25 — vista previa inline del PDF */}
      {showPreview && doc.file_type === "pdf" && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <iframe
            src={docDownloadUrl(doc.id)}
            title={`Vista previa de ${doc.filename}`}
            className="w-full h-[70vh]"
          />
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <div className="flex gap-6">
          <button
            onClick={() => setActiveTab("content")}
            className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "content"
                ? "border-violet-600 text-violet-700"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            <span className="flex items-center gap-1.5">
              <BookOpen className="w-4 h-4" />
              Contenido extraído
            </span>
          </button>
          <button
            onClick={() => setActiveTab("chunks")}
            className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "chunks"
                ? "border-violet-600 text-violet-700"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            <span className="flex items-center gap-1.5">
              <Layers className="w-4 h-4" />
              Chunks ({chunkCount})
            </span>
          </button>
          <button
            onClick={() => setActiveTab("history")}
            className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "history"
                ? "border-violet-600 text-violet-700"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            <span className="flex items-center gap-1.5">
              <Clock className="w-4 h-4" />
              Historial ({history.length})
            </span>
          </button>
        </div>
      </div>

      {/* Tab content */}
      <div>
        {activeTab === "content" && (
          <div className="bg-white border border-gray-200 rounded-xl p-5">
            {content?.content ? (
              <pre className="text-sm text-gray-700 whitespace-pre-wrap font-sans leading-relaxed max-h-[60vh] overflow-y-auto">
                {content.content}
              </pre>
            ) : (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <FileText className="w-10 h-10 text-gray-300 mb-3" />
                <p className="text-gray-500 font-medium">
                  Sin contenido extraído
                </p>
                <p className="text-sm text-gray-400 mt-1">
                  El documento aún no ha sido procesado por el pipeline de
                  curación.
                </p>
              </div>
            )}
          </div>
        )}

        {activeTab === "chunks" && (
          <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
            {content?.chunks.length ? (
              content.chunks.map((chunk) => (
                <div
                  key={chunk.chunk_index}
                  className="bg-white border border-gray-200 rounded-xl p-4"
                >
                  <div className="flex items-center justify-between mb-2 text-xs text-gray-400">
                    <span className="font-mono">
                      Chunk #{chunk.chunk_index + 1}
                    </span>
                    <div className="flex items-center gap-3">
                      {chunk.page_number != null && (
                        <span>Pág. {chunk.page_number}</span>
                      )}
                      <span>{chunk.token_count} tokens</span>
                    </div>
                  </div>
                  <p className="text-sm text-gray-700 whitespace-pre-wrap font-sans leading-relaxed line-clamp-6">
                    {chunk.content}
                  </p>
                </div>
              ))
            ) : (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <Layers className="w-10 h-10 text-gray-300 mb-3" />
                <p className="text-gray-500 font-medium">Sin chunks</p>
                <p className="text-sm text-gray-400 mt-1">
                  No hay chunks disponibles para este documento.
                </p>
              </div>
            )}
          </div>
        )}

        {activeTab === "history" && (
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            {history.length ? (
              <div className="divide-y divide-gray-100">
                {history.map((h) => (
                  <div key={h.id} className="px-5 py-4">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-gray-800">
                        {ACTION_LABELS[h.action] ?? h.action}
                      </span>
                      <span className="text-xs text-gray-400">
                        {fmtDate(h.timestamp)}
                      </span>
                    </div>
                    {h.reason && (
                      <p className="text-xs text-gray-500 mt-1">{h.reason}</p>
                    )}
                    {h.after_content && (
                      <p className="text-xs text-gray-400 mt-0.5 font-mono">
                        {JSON.stringify(h.after_content)}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <Clock className="w-10 h-10 text-gray-300 mb-3" />
                <p className="text-gray-500 font-medium">
                  Sin historial de cambios
                </p>
                <p className="text-sm text-gray-400 mt-1">
                  No se han registrado cambios en el estado de este documento.
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
