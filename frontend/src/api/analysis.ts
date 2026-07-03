import api from "./axios";

export interface CurationRun {
  thread_id: string;
  status: string;
  error: string | null;
  result: Record<string, unknown> | null;
  trace_url?: string;
}

export interface CurationResponse {
  status: string;
  thread_id: string;
  message: string;
}

export interface CurationInfo {
  nodes: string[];
  checkpointer: string;
  tools: string[];
  llm: string;
  tracing: {
    langfuse: boolean;
    langfuse_configured: boolean;
  };
}

/** Dispara el pipeline completo de curación en segundo plano. */
export const triggerCuration = () =>
  api.post<CurationResponse>("/api/analysis/curate");

/** Consulta el estado de una corrida por su thread_id. */
export const getCurationStatus = (threadId: string) =>
  api.get<CurationRun>(`/api/analysis/status/${threadId}`);

/** Retorna información del grafo de curación (LLM, tools, tracing). */
export const getAnalysisInfo = () =>
  api.get<CurationInfo>("/api/analysis/info");
