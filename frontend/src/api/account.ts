import api from "./axios";

// ── HU-29: registro y perfil académico ───────────────────────────────────────

export interface RegisterPayload {
  email: string;
  password: string;
  full_name: string;
  profession?: string;
  subjects: string[];
  specialties?: string[];
  courses_taught?: string[];
}

export interface UserProfile {
  id: string;
  email: string;
  full_name: string | null;
  profession: string | null;
  subjects: string[] | null;
  specialties: string[] | null;
  courses_taught: string[] | null;
  role: "instructor" | "admin";
  is_active: boolean;
  created_at: string | null;
}

export const register = (payload: RegisterPayload) =>
  api.post<{ access_token: string; token_type: string }>(
    "/auth/register",
    payload,
  );

export const getMyProfile = () => api.get<UserProfile>("/api/users/me");

export const updateMyProfile = (payload: Partial<RegisterPayload>) =>
  api.patch<UserProfile>("/api/users/me", payload);

// ── HU-30: administración de usuarios y roles ────────────────────────────────

export interface AdminUser {
  id: string;
  email: string;
  full_name: string | null;
  profession: string | null;
  role: "instructor" | "admin";
  is_active: boolean;
}

export interface Role {
  id: string;
  name: string;
  description: string | null;
  permissions: string[] | null;
  is_system: boolean;
  users_count: number;
}

export interface RoleAuditEntry {
  id: string;
  action: string;
  performed_by: string | null;
  reason: string | null;
  before_content: Record<string, unknown> | null;
  after_content: Record<string, unknown> | null;
  timestamp: string;
}

export const listUsers = () => api.get<AdminUser[]>("/api/users");

export const listRoles = () => api.get<Role[]>("/api/roles");

export const createRole = (payload: {
  name: string;
  description?: string;
  permissions?: string[];
}) => api.post<Role>("/api/roles", payload);

export const deleteRole = (id: string) => api.delete(`/api/roles/${id}`);

export const assignUserRole = (userId: string, role: "instructor" | "admin") =>
  api.patch<UserProfile>(`/api/users/${userId}/role`, { role });

export const getRoleAudit = (limit = 50) =>
  api.get<RoleAuditEntry[]>("/api/users/role-audit", { params: { limit } });

// ── HU-20: panel de inicio ───────────────────────────────────────────────────

export interface DashboardData {
  recent_documents: {
    id: string;
    filename: string;
    status: string;
    uploaded_at: string | null;
    suggestions_count: number;
  }[];
  pending_documents: {
    id: string;
    filename: string;
    status: string;
    pending_suggestions: number;
  }[];
  metrics: {
    total_documents: number;
    total_suggestions: number;
    pending_suggestions: number;
    approved_suggestions: number;
    rejected_suggestions: number;
    approval_rate: number;
  };
  last_run: {
    thread_id: string;
    status: string;
    started_at: string | null;
    duration_seconds: number | null;
    suggestions_generated: number;
  } | null;
}

export const getDashboard = () =>
  api.get<DashboardData>("/api/analytics/dashboard");

// ── HU-32: consumo de tokens ─────────────────────────────────────────────────

export interface TokenAnalytics {
  period_days: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  total_cost_usd: number;
  calls: number;
  last_run: {
    thread_id: string | null;
    total_tokens: number;
    cost_usd: number;
  };
  by_operation: Record<string, { tokens: number; cost_usd: number }>;
  by_model: Record<string, { tokens: number; cost_usd: number }>;
  daily: { date: string; tokens: number; cost_usd: number }[];
  rates: { input_per_1k: number; output_per_1k: number };
  estimated: boolean;
}

export const getTokenAnalytics = (days = 30) =>
  api.get<TokenAnalytics>("/api/analytics/tokens", { params: { days } });

// ── HU-31: chat en lenguaje natural ──────────────────────────────────────────

export interface ChatSource {
  doc_id: string;
  doc_name: string;
  chunk_index: number;
  excerpt: string;
  similarity: number;
}

export interface ChatAnswer {
  answer: string;
  sources: ChatSource[];
  confidence: number;
  has_context: boolean;
  model: string | null;
}

export const askChat = (question: string, docIds?: string[]) =>
  api.post<ChatAnswer>("/api/chat", {
    question,
    doc_ids: docIds && docIds.length > 0 ? docIds : undefined,
  });
