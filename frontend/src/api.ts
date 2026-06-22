import axios from "axios";
import axiosRetry from "axios-retry";
import type { GraphData, QuestionResponse, ReportSummary, Workspace, Source } from "./types";

// Default to same-origin ("") so requests go through Vite's /api proxy in dev
// (and through whatever serves the built frontend in prod). Set VITE_API_URL to
// point directly at a backend if you need to bypass the proxy.
const BASE_URL = import.meta.env.VITE_API_URL ?? "";

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

  // Track whether the stream completed successfully so we can ignore the
  // connection-close error that fires after we call es.close() on done.
  let finished = false;

  es.addEventListener("routing", (e) => {
    try { callbacks.onRouting?.(JSON.parse(e.data).type); } catch {}
  });
  es.addEventListener("progress", (e) => {
    try { callbacks.onProgress?.(JSON.parse(e.data).status); } catch {}
  });
  es.addEventListener("done", (e) => {
    finished = true;
    try { callbacks.onDone?.(JSON.parse(e.data)); } catch {}
    es.close();
  });

  // The "error" listener catches two different things:
  //   1. Server-sent `event: error` frames → e.data has JSON payload
  //   2. Native connection errors (backend down, 404, CORS) → e.data is null
  // We ignore errors after a successful done to avoid a spurious call on close.
  es.addEventListener("error", (e) => {
    if (finished) return;

    const data = (e as MessageEvent).data;
    if (data) {
      // Server explicitly sent an error event with a payload
      try {
        const d = JSON.parse(data);
        callbacks.onError?.(d.detail ?? "The server reported an error.");
      } catch {
        callbacks.onError?.("The server reported an error.");
      }
      es.close();
    } else {
      // Connection-level failure — fall back to regular POST so the user
      // still gets an answer even if streaming isn't available.
      es.close();
      callbacks.onProgress?.("Falling back to direct request…");
      askQuestion(question, workspaceId)
        .then((result) => callbacks.onDone?.(result))
        .catch(() =>
          callbacks.onError?.(
            "Couldn't reach the backend. Make sure it's running on port 8000.",
          ),
        );
    }
  });

  return () => {
    finished = true;
    es.close();
  };
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

export async function updateWorkspace(
  workspaceId: string,
  fields: { name?: string; domain?: string; description?: string },
) {
  const { data } = await client.put<Workspace>(`/api/workspaces/${workspaceId}`, fields);
  return data;
}

export async function deleteWorkspace(workspaceId: string) {
  await client.delete(`/api/workspaces/${workspaceId}`);
}

export async function deleteReport(reportId: string) {
  await client.delete(`/api/reports/${reportId}`);
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

export async function getSourceJobs(workspaceId: string, sourceId: string, limit = 50) {
  const { data } = await client.get<import("./types").SourceJobsResponse>(
    `/api/workspaces/${workspaceId}/sources/${sourceId}/jobs`,
    { params: { limit } },
  );
  return data;
}

export async function retrySource(workspaceId: string, sourceId: string) {
  const { data } = await client.post<{ status: string; source: Source }>(
    `/api/workspaces/${workspaceId}/sources/${sourceId}/retry`,
  );
  return data;
}

export async function getQueueStatus() {
  const { data } = await client.get<import("./types").QueueStatus>("/api/system/queue");
  return data;
}
