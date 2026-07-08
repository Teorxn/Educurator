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

export interface AgentRun {
  thread_id: string;
  status: string;
  triggered_by: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  documents_processed: number;
  suggestions_generated: number;
  summary: {
    suggestions_by_type?: Record<string, number>;
    redundancy_pairs?: number;
    inconsistency_findings?: number;
    pipeline_error?: string | null;
  } | null;
  error: string | null;
  trace_url: string | null;
}

export interface AgentRunsResponse {
  total: number;
  runs: AgentRun[];
}

/** Dispara el pipeline completo de curación en segundo plano. */
export const triggerCuration = () =>
  api.post<CurationResponse>("/api/analysis/curate");

/** HU-19 — Histórico persistente de ejecuciones del agente. */
export const getCurationRuns = (limit = 50) =>
  api.get<AgentRunsResponse>("/api/analysis/runs", { params: { limit } });

export interface GraphDiagram {
  mermaid: string;
  nodes: string[];
  llm: string;
}

/** Diagrama Mermaid del grafo LangGraph (generado del grafo compilado). */
export const getGraphDiagram = () =>
  api.get<GraphDiagram>("/api/analysis/graph");

/** Consulta el estado de una corrida por su thread_id. */
export const getCurationStatus = (threadId: string) =>
  api.get<CurationRun>(`/api/analysis/status/${threadId}`);

/** Retorna información del grafo de curación (LLM, tools, tracing). */
export const getAnalysisInfo = () =>
  api.get<CurationInfo>("/api/analysis/info");
