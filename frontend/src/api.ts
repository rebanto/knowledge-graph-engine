import axios from "axios";
import type { QuestionResponse, ReportSummary } from "./types";

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
