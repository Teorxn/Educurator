import api from "./axios";

export type SuggestionType =
  "redundancy" | "conflict" | "faq" | "update" | "inconsistency";
export type SuggestionStatus = "pending" | "approved" | "rejected";

// Severidad para hallazgos de inconsistencia
export type SeverityLevel = "high" | "medium" | "low";

export interface InconsistencyEvidence {
  chunk_id_a: string;
  chunk_id_b: string;
  doc_id_a: string;
  doc_id_b: string;
  extract_a: string;
  extract_b: string;
  description: string;
  suggestion: string;
  severity: SeverityLevel;
  type: "self_contradiction" | "terminology" | "numerical" | "structural";
}

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
  type: SuggestionType;
  status: SuggestionStatus;
  description: string;
  reasoning: string | null;
  confidence_score: number;
  source_chunk_ids: string[];
  source_chunks: ChunkEvidence[];
  source_doc_id: string;
  source_web_url: string | null;
  source_type: string | null;
  review_reason: string | null;
  reviewed_by: string | null;
  /** HU-26 — identidad legible del revisor */
  reviewed_by_email?: string | null;
  reviewed_by_name?: string | null;
  created_at: string;
  reviewed_at: string | null;
}

export interface SuggestionsListResponse {
  items: Suggestion[];
  total: number;
}

export interface AnalyticsData {
  total_documents: number;
  by_status: Record<string, number>;
  total_suggestions: number;
  suggestions_by_status: Record<string, number>;
  suggestions_by_type: Record<string, number>;
  approval_rate: number;
}

export const getSuggestions = (params?: {
  status?: string;
  type?: string;
  doc_id?: string;
  page?: number;
  limit?: number;
}) => api.get<SuggestionsListResponse>("/api/suggestions", { params });

export const approveSuggestion = (id: string) =>
  api.post<Suggestion>(`/api/suggestions/${id}/approve`);

export const rejectSuggestion = (id: string, reason: string) =>
  api.post<Suggestion>(`/api/suggestions/${id}/reject`, { reason });

export const addFeedback = (id: string, comment?: string) =>
  api.post(`/api/suggestions/${id}/feedback`, { comment });

export const getAnalytics = () => api.get<AnalyticsData>("/api/analytics");
