import axios from "axios";
import type { GraphData, QuestionResponse, ReportSummary, Workspace, Source } from "./types";

const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000",
});

export async function askQuestion(question: string, workspaceId = "arxiv_seed") {
  const { data } = await client.post<QuestionResponse>("/api/question", {
    question,
    workspace_id: workspaceId,
  });
  return data;
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

export async function createWorkspace(name: string, domain: string) {
  const { data } = await client.post<Workspace>("/api/workspaces", { name, domain });
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
