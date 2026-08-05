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
      <div className="flex items-center justify-center h-64 text-ink-3 gap-2">
        <RefreshCw className="w-5 h-5 animate-spin" />
        <span className="text-sm">Cargando documento...</span>
      </div>
    );
  }

  if (error || !doc) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-center">
        <div className="w-14 h-14 bg-danger-soft rounded-2xl flex items-center justify-center mb-4">
          <FileText className="w-7 h-7 text-danger-fg" />
        </div>
        <p className="text-ink-2 font-medium">
          {error || "No se pudo cargar el documento"}
        </p>
        <button
          onClick={() => navigate("/docs")}
          className="btn btn-primary mt-4"
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
        className="inline-flex items-center gap-1.5 text-sm text-ink-2 hover:text-brand-hover transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Volver a documentos
      </button>

      {/* Header card */}
      <div className="card p-5">
        <div className="flex items-start gap-3">
          <span className="text-2xl">{FILE_EMOJI[doc.file_type] ?? "📄"}</span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-lg font-semibold text-ink truncate">
                {doc.filename}
              </h2>
              {doc.category === "reference" && (
                <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-warning-soft text-warning-fg shrink-0">
                  📖 Referencia
                </span>
              )}
            </div>
            {content?.original_filename &&
              content.original_filename !== doc.filename && (
                <p className="text-xs text-ink-3 mt-0.5">
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
                className="p-2 rounded-md text-ink-3 hover:text-brand-hover hover:bg-brand-soft transition-colors"
                title={showPreview ? "Ocultar vista previa" : "Vista previa"}
              >
                <Eye className="w-4 h-4" />
              </button>
            )}
            <button
              onClick={handleDownload}
              className="p-2 rounded-md text-ink-3 hover:text-brand-hover hover:bg-brand-soft transition-colors"
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
                  className="btn btn-danger btn-sm"
                >
                  {deleting ? "Eliminando..." : "Confirmar"}
                </button>
                <button
                  onClick={() => setConfirmDelete(false)}
                  disabled={deleting}
                  className="text-xs font-medium px-2.5 py-1.5 rounded-md bg-surface-2 text-ink-2 hover:bg-surface-3 transition-colors"
                >
                  Cancelar
                </button>
              </div>
            ) : (
              <button
                onClick={() => setConfirmDelete(true)}
                className="p-2 rounded-md text-ink-3 hover:text-danger-fg hover:bg-danger-soft transition-colors"
                title="Eliminar documento"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>

        {/* Metadata grid */}
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
          <div className="flex items-center gap-2 text-ink-2">
            <HardDrive className="w-3.5 h-3.5 shrink-0" />
            <span>{fmtSize(doc.size_bytes)}</span>
          </div>
          <div className="flex items-center gap-2 text-ink-2">
            <Hash className="w-3.5 h-3.5 shrink-0" />
            <span className="uppercase">{doc.file_type}</span>
          </div>
          <div className="flex items-center gap-2 text-ink-2">
            <Clock className="w-3.5 h-3.5 shrink-0" />
            <span>{fmtDate(doc.uploaded_at)}</span>
          </div>
          <div className="flex items-center gap-2 text-ink-2">
            <Layers className="w-3.5 h-3.5 shrink-0" />
            <span>
              {chunkCount} chunk{chunkCount !== 1 ? "s" : ""} ·{" "}
              {totalTokens.toLocaleString()} tokens
            </span>
          </div>
          {/* HU-25 — uploader */}
          {detail?.uploader_email && (
            <div className="flex items-center gap-2 text-ink-2">
              <UserIcon className="w-3.5 h-3.5 shrink-0" />
              <span className="truncate">{detail.uploader_email}</span>
            </div>
          )}
        </div>

        {/* HU-23 — mensaje de error del pipeline */}
        {doc.status === "error" && doc.error_message && (
          <div className="flex items-start gap-2 mt-3 text-sm text-danger-fg bg-danger-soft border border-transparent rounded-lg px-3 py-2">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            {doc.error_message}
          </div>
        )}

        {/* HU-27 — aprobación del documento */}
        {detail && doc.status !== "approved" && (
          <div className="flex items-center justify-between gap-3 mt-4 pt-3 border-t border-line flex-wrap">
            <p className="text-xs text-ink-2">
              {pendingSuggestions > 0 ? (
                <>
                  No puedes aprobar este documento:{" "}
                  <strong className="text-warning-fg">
                    {pendingSuggestions} sugerencia
                    {pendingSuggestions !== 1 ? "s" : ""}
                  </strong>{" "}
                  {pendingSuggestions !== 1 ? "están" : "está"} pendiente
                  {pendingSuggestions !== 1 ? "s" : ""} de revisión.{" "}
                  <button
                    onClick={() => navigate(`/review?document_id=${doc.id}`)}
                    className="text-brand hover:text-brand-hover font-medium"
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
              className="btn btn-success btn-sm"
            >
              <CheckCircle2 className="w-4 h-4" />
              {approving ? "Aprobando..." : "Aprobar documento"}
            </button>
          </div>
        )}

        {approveError && (
          <div className="flex items-start gap-2 mt-2 text-sm text-danger-fg bg-danger-soft border border-transparent rounded-lg px-3 py-2">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            {approveError}
          </div>
        )}
      </div>

      {/* HU-25 — vista previa inline del PDF */}
      {showPreview && doc.file_type === "pdf" && (
        <div className="card overflow-hidden">
          <iframe
            src={docDownloadUrl(doc.id)}
            title={`Vista previa de ${doc.filename}`}
            className="w-full h-[70vh]"
          />
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-line">
        <div className="flex gap-6">
          <button
            onClick={() => setActiveTab("content")}
            className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "content"
                ? "border-brand text-brand"
                : "border-transparent text-ink-2 hover:text-ink"
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
                ? "border-brand text-brand"
                : "border-transparent text-ink-2 hover:text-ink"
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
                ? "border-brand text-brand"
                : "border-transparent text-ink-2 hover:text-ink"
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
          <div className="card p-5">
            {content?.content ? (
              <pre className="text-sm text-ink whitespace-pre-wrap font-sans leading-relaxed max-h-[60vh] overflow-y-auto">
                {content.content}
              </pre>
            ) : (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <FileText className="w-10 h-10 text-ink-3 mb-3" />
                <p className="text-ink-2 font-medium">
                  Sin contenido extraído
                </p>
                <p className="text-sm text-ink-3 mt-1">
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
                  className="card p-4"
                >
                  <div className="flex items-center justify-between mb-2 text-xs text-ink-3">
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
                  <p className="text-sm text-ink whitespace-pre-wrap font-sans leading-relaxed line-clamp-6">
                    {chunk.content}
                  </p>
                </div>
              ))
            ) : (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <Layers className="w-10 h-10 text-ink-3 mb-3" />
                <p className="text-ink-2 font-medium">Sin chunks</p>
                <p className="text-sm text-ink-3 mt-1">
                  No hay chunks disponibles para este documento.
                </p>
              </div>
            )}
          </div>
        )}

        {activeTab === "history" && (
          <div className="card overflow-hidden">
            {history.length ? (
              <div className="divide-y divide-line">
                {history.map((h) => (
                  <div key={h.id} className="px-5 py-4">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-ink">
                        {ACTION_LABELS[h.action] ?? h.action}
                      </span>
                      <span className="text-xs text-ink-3">
                        {fmtDate(h.timestamp)}
                      </span>
                    </div>
                    {h.reason && (
                      <p className="text-xs text-ink-2 mt-1">{h.reason}</p>
                    )}
                    {h.after_content && (
                      <p className="text-xs text-ink-3 mt-0.5 font-mono">
                        {JSON.stringify(h.after_content)}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <Clock className="w-10 h-10 text-ink-3 mb-3" />
                <p className="text-ink-2 font-medium">
                  Sin historial de cambios
                </p>
                <p className="text-sm text-ink-3 mt-1">
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
