import api from "./axios";

export type SuggestionType = "redundancy" | "conflict" | "faq" | "update";
export type SuggestionStatus = "pending" | "approved" | "rejected";

export interface ChunkEvidence {
  chunk_id: string;
  content: string;
  chunk_index: number;
  token_count: number;
  page_number: number | null;
}

export interface Suggestion {
  id: string;
  doc_id: string;
  type: SuggestionType;
  status: SuggestionStatus;
  description: string;
  reasoning: string | null;
  confidence_score: number | null;
  source_chunk_ids: string[] | null;
  source_chunks: ChunkEvidence[];
  source_doc_id: string | null;
  rejection_reason: string | null;
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
