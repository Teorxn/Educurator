import api from "./axios";

export interface ReferenceDoc {
  id: string;
  filename: string;
  file_type: "pdf" | "docx" | "txt";
  status: "needs_review" | "processing" | "approved" | "rejected" | "archived";
  uploaded_at: string;
  size_bytes: number;
}

export interface ReferenceDocsResponse {
  items: ReferenceDoc[];
  total: number;
}

export interface ReferenceDocProcessResult {
  status: string;
  doc_id: string | null;
  chunks_count: number | null;
  error: string | null;
}

export const getReferenceDocs = (params?: {
  page?: number;
  limit?: number;
}) => api.get<ReferenceDocsResponse>("/api/reference-docs", { params });

export const getReferenceDoc = (id: string) =>
  api.get<ReferenceDoc>(`/api/reference-docs/${id}`);

export const uploadReferenceDoc = (
  file: File,
  onProgress?: (pct: number) => void,
) => {
  const form = new FormData();
  form.append("file", file);
  return api.post<ReferenceDoc>("/api/reference-docs/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (e) => {
      if (onProgress && e.total)
        onProgress(Math.round((e.loaded * 100) / e.total));
    },
  });
};

export const deleteReferenceDoc = (id: string) =>
  api.delete<{ status: string; message: string }>(`/api/reference-docs/${id}`);

export const processReferenceDocs = () =>
  api.post<ReferenceDocProcessResult[]>("/api/reference-docs/process");
