import { useCallback, useState, useRef } from "react";
import type { DragEvent, ChangeEvent } from "react";
import {
  Upload as UploadIcon,
  File,
  X,
  CheckCircle2,
  AlertCircle,
  Loader2,
} from "lucide-react";
import { uploadDoc } from "../api/docs";

const ACCEPTED_MIME = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
];
const ACCEPTED_EXT = [".pdf", ".docx", ".txt"];
const MAX_BYTES = 50 * 1024 * 1024;

type UploadState = "idle" | "uploading" | "success" | "error";

function validateFile(f: File): string | null {
  const okMime = ACCEPTED_MIME.includes(f.type);
  const okExt = ACCEPTED_EXT.some((ext) => f.name.toLowerCase().endsWith(ext));
  if (!okMime && !okExt) return "Tipo no soportado. Solo PDF, DOCX y TXT.";
  if (f.size > MAX_BYTES) return "El archivo supera el límite de 50 MB.";
  return null;
}

function fmtSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function Upload() {
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [state, setState] = useState<UploadState>("idle");
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

  const onDragOver = (e: DragEvent) => {
    e.preventDefault();
    setDragging(true);
  };
  const onDragLeave = () => setDragging(false);
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  };
  const onInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) handleFile(f);
  };

  const handleUpload = async () => {
    if (!file) return;
    setState("uploading");
    setProgress(0);
    try {
      await uploadDoc(file, setProgress);
      setProgress(100);
      setState("success");
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
    <div className="max-w-2xl space-y-4">
      {/* Drop zone */}
      <div
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => !file && inputRef.current?.click()}
        className={`
          border-2 border-dashed rounded-2xl p-12 text-center transition-all
          ${!file ? "cursor-pointer" : ""}
          ${
            dragging
              ? "border-violet-500 bg-violet-50"
              : "border-gray-200 bg-white hover:border-violet-300 hover:bg-gray-50"
          }
        `}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_EXT.join(",")}
          onChange={onInputChange}
          className="hidden"
        />

        {!file ? (
          <>
            <div className="w-16 h-16 bg-violet-50 rounded-2xl flex items-center justify-center mx-auto mb-4">
              <UploadIcon className="w-8 h-8 text-violet-500" />
            </div>
            <p className="text-gray-700 font-medium mb-1">
              {dragging
                ? "Suelta el archivo aquí"
                : "Arrastra un archivo o haz clic para seleccionar"}
            </p>
            <p className="text-sm text-gray-400">
              PDF, DOCX o TXT · máx. 50 MB
            </p>
          </>
        ) : (
          <div className="flex flex-col items-center gap-3">
            <div className="w-12 h-12 bg-blue-50 rounded-xl flex items-center justify-center">
              <File className="w-6 h-6 text-blue-500" />
            </div>
            <div>
              <p className="font-medium text-gray-800">{file.name}</p>
              <p className="text-xs text-gray-400 mt-0.5">
                {fmtSize(file.size)}
              </p>
            </div>
            {state === "idle" && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  reset();
                }}
                className="text-gray-400 hover:text-gray-600 transition-colors"
                title="Quitar archivo"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
        )}
      </div>

      {/* Validation error */}
      {errorMsg && state !== "error" && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {errorMsg}
        </div>
      )}

      {/* Progress bar */}
      {state === "uploading" && (
        <div>
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

      {/* Success */}
      {state === "success" && (
        <div className="flex items-center gap-2 bg-green-50 border border-green-200 text-green-800 text-sm rounded-xl px-4 py-3">
          <CheckCircle2 className="w-4 h-4 shrink-0 text-green-600" />
          <span>
            ¡Documento subido! El agente comenzará a procesarlo pronto.
          </span>
          <button
            onClick={reset}
            className="ml-auto text-green-700 hover:underline font-medium shrink-0"
          >
            Subir otro
          </button>
        </div>
      )}

      {/* Upload error */}
      {state === "error" && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3">
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

      {/* Action button */}
      {file && state === "idle" && (
        <button
          onClick={handleUpload}
          className="w-full bg-violet-600 hover:bg-violet-700 text-white font-medium py-2.5 px-4 rounded-xl transition-colors flex items-center justify-center gap-2"
        >
          <UploadIcon className="w-4 h-4" />
          Subir documento
        </button>
      )}

      {state === "uploading" && (
        <button
          disabled
          className="w-full bg-violet-300 text-white font-medium py-2.5 px-4 rounded-xl flex items-center justify-center gap-2 cursor-not-allowed"
        >
          <Loader2 className="w-4 h-4 animate-spin" />
          Subiendo...
        </button>
      )}
    </div>
  );
}
