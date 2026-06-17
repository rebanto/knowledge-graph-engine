import axios from "axios";
import axiosRetry from "axios-retry";
import type { GraphData, QuestionResponse, ReportSummary, Workspace, Source } from "./types";

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 45_000,
});

// Retry on network errors and 5xx responses, exponential backoff
axiosRetry(client, {
  retries: 3,
  retryDelay: axiosRetry.exponentialDelay,
  retryCondition: (err) =>
    axiosRetry.isNetworkOrIdempotentRequestError(err) ||
    (err.response?.status ?? 0) >= 500,
  shouldResetTimeout: true,
});

export async function askQuestion(
  question: string,
  workspaceId = "arxiv_seed",
  signal?: AbortSignal,
) {
  const { data } = await client.post<QuestionResponse>(
    "/api/question",
    { question, workspace_id: workspaceId },
    { signal },
  );
  return data;
}

export function streamQuestion(
  question: string,
  workspaceId = "arxiv_seed",
  callbacks: {
    onRouting?: (type: string) => void;
    onProgress?: (status: string) => void;
    onDone?: (result: QuestionResponse) => void;
    onError?: (detail: string) => void;
  },
): () => void {
  const params = new URLSearchParams({ question, workspace_id: workspaceId });
  const es = new EventSource(`${BASE_URL}/api/question/stream?${params}`);

  es.addEventListener("routing", (e) => {
    try { callbacks.onRouting?.(JSON.parse(e.data).type); } catch {}
  });
  es.addEventListener("progress", (e) => {
    try { callbacks.onProgress?.(JSON.parse(e.data).status); } catch {}
  });
  es.addEventListener("done", (e) => {
    try { callbacks.onDone?.(JSON.parse(e.data)); } catch {}
    es.close();
  });
  es.addEventListener("error", (e) => {
    try {
      const d = JSON.parse((e as MessageEvent).data ?? "{}");
      callbacks.onError?.(d.detail ?? "Streaming failed.");
    } catch {
      callbacks.onError?.("Streaming failed.");
    }
    es.close();
  });

  return () => es.close();
}

export async function listReports(workspaceId = "arxiv_seed") {
  const { data } = await client.get<ReportSummary[]>("/api/reports", {
    params: { workspace_id: workspaceId },
  });
  return data;
}

export async function getReport(reportId: string) {
  const { data } = await client.get<QuestionResponse>(`/api/reports/${reportId}`);
  return data;
}

export async function getGraph(workspaceId = "arxiv_seed", limit = 150) {
  const { data } = await client.get<GraphData>("/api/graph", {
    params: { workspace_id: workspaceId, limit },
  });
  return data;
}

export async function listWorkspaces() {
  const { data } = await client.get<Workspace[]>("/api/workspaces");
  return data;
}

export async function createWorkspace(name: string, domain: string, description?: string) {
  const { data } = await client.post<Workspace>("/api/workspaces", { name, domain, description });
  return data;
}

export async function discoverSources(workspaceId: string) {
  const { data } = await client.post<Source[]>(`/api/workspaces/${workspaceId}/discover`);
  return data;
}

export async function listSources(workspaceId: string) {
  const { data } = await client.get<Source[]>(`/api/workspaces/${workspaceId}/sources`);
  return data;
}

export async function createSource(workspaceId: string, type: string, url: string) {
  const { data } = await client.post<Source>(`/api/workspaces/${workspaceId}/sources`, { type, url });
  return data;
}

export async function deleteSource(workspaceId: string, sourceId: string) {
  await client.delete(`/api/workspaces/${workspaceId}/sources/${sourceId}`);
}

export async function uploadPdf(workspaceId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  const { data } = await client.post<Source>(
    `/api/workspaces/${workspaceId}/sources/upload`,
    form,
  );
  return data;
}
