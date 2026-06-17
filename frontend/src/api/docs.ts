import api from "./axios";

export interface Document {
  id: string;
  filename: string;
  file_type: "pdf" | "docx" | "txt";
  status: "needs_review" | "processing" | "approved" | "rejected" | "archived";
  uploaded_at: string;
  size_bytes: number;
}

export interface DocsResponse {
  items: Document[];
  total: number;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
}

export const login = (email: string, password: string) =>
  api.post<AuthResponse>("/auth/login", { email, password });

export const getDocs = (params?: {
  status?: string;
  page?: number;
  limit?: number;
}) => api.get<DocsResponse>("/api/docs", { params });

export const uploadDoc = (file: File, onProgress?: (pct: number) => void) => {
  const form = new FormData();
  form.append("file", file);
  return api.post<Document>("/api/docs/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (e) => {
      if (onProgress && e.total)
        onProgress(Math.round((e.loaded * 100) / e.total));
    },
  });
};

// ── Suggestions ──────────────────────────────────────────────────────────────

export interface ChunkEvidence {
  chunk_id: string;
  content: string;
  chunk_index: number;
  token_count: number;
  page_number: number | null;
}

export interface Suggestion {
  id: string;
  document_id: string;
  document_name: string | null;
  type: "redundancy" | "conflict" | "faq" | "update";
  description: string;
  source_doc_id: string;
  source_chunk_ids: string[];
  source_chunks: ChunkEvidence[];
  confidence_score: number;
  reasoning: string | null;
  status: "pending" | "approved" | "rejected";
  reviewed_by: string | null;
  review_reason: string | null;
  created_at: string;
  reviewed_at: string | null;
}

export interface SuggestionsResponse {
  items: Suggestion[];
  total: number;
}

export const getSuggestions = (params?: {
  status?: string;
  type?: string;
  document_id?: string;
  page?: number;
  limit?: number;
}) => api.get<SuggestionsResponse>("/api/suggestions", { params });

export const approveSuggestion = (id: string) =>
  api.post<{ id: string; status: string; message: string }>(
    `/api/suggestions/${id}/approve`,
  );

export const rejectSuggestion = (id: string, reason: string) =>
  api.post<{ id: string; status: string; message: string }>(
    `/api/suggestions/${id}/reject`,
    { reason },
  );
