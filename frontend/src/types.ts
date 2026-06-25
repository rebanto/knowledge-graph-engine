export type RetrievalType = "graph" | "vector" | "hybrid";

export interface GraphRecord {
  [key: string]: string | number | boolean | null;
}

export interface VectorChunk {
  text: string;
  source_title: string | null;
  source_url: string | null;
  distance: number;
}

// ── Structured insights returned by the backend synthesizer ──────────────────

export interface BarChartPoint {
  name: string;
  value: number;
}

export interface FlowStep {
  entity: string;
  entity_type: string;
  relation: string | null;
}

export interface StatItem {
  label: string;
  value: string;
  subtitle?: string | null;
}

export interface ComparisonRow extends Array<string> {}

export interface TimelineEvent {
  year: string;
  label: string;
  detail?: string | null;
}

export interface BarChartInsight {
  type: "bar_chart";
  title?: string;
  x_label?: string;
  y_label?: string;
  color?: string;
  data: BarChartPoint[];
}

export interface FlowPathInsight {
  type: "flow_path";
  title?: string;
  steps: FlowStep[];
}

export interface StatGridInsight {
  type: "stat_grid";
  stats: StatItem[];
}

export interface ComparisonTableInsight {
  type: "comparison_table";
  title?: string;
  columns: string[];
  rows: ComparisonRow[];
}

export interface TimelineInsight {
  type: "timeline";
  title?: string;
  events: TimelineEvent[];
}

export type Insight =
  | BarChartInsight
  | FlowPathInsight
  | StatGridInsight
  | ComparisonTableInsight
  | TimelineInsight;

export interface KeyEntity {
  name: string;
  type: string;
  role: string;
}

export interface Conflict {
  source: string;
  target: string;
  claim_types: string[];
  documents: string[];
}

// ── Question / report types ──────────────────────────────────────────────────

export interface QuestionResponse {
  id: string;
  question: string;
  answer: string;
  retrieval_type: RetrievalType;
  reasoning: string;
  cypher: string | null;
  graph_records: GraphRecord[];
  vector_chunks: VectorChunk[];
  key_entities: KeyEntity[];
  insights: Insight[];
  conflicts: Conflict[];
  version: number;
  cached: boolean;
  created_at: string;
}

export interface ReportSummary {
  id: string;
  question: string;
  answer: string;
  retrieval_type: RetrievalType;
  version: number;
  created_at: string;
}

// ── Graph view types ─────────────────────────────────────────────────────────

export type NodeType = "Person" | "Organization" | "Paper" | "Concept" | "Event" | "Topic";

export interface GraphNode {
  name: string;
  type: NodeType;
  degree: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  confidence: number | null;
  conflict: boolean;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ── Workspace / source types ─────────────────────────────────────────────────

export interface Workspace {
  id: string;
  name: string;
  domain: string;
  description?: string | null;
  created_at: string;
}

export type SourceType = "arxiv_feed" | "rss" | "web_url" | "pdf_upload";
export type SourceStatus = "pending" | "running" | "success" | "error";

export interface Source {
  id: string;
  workspace_id: string;
  type: SourceType;
  url: string;
  status: SourceStatus;
  error_count: number;
  last_error: string | null;
  last_fetched: string | null;
  created_at: string;
}

export interface IngestionJob {
  id: string;
  document_url: string | null;
  status: "running" | "success" | "failed";
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface SourceJobsResponse {
  total: number;
  success: number;
  failed: number;
  running: number;
  jobs: IngestionJob[];
}

export interface WorkerInfo {
  name: string;
  state: string;
  queues: string[];
  current_job_id: string | null;
}

export interface QueueInfo {
  queued: number;
  started: number;
  failed: number;
}

export interface QueueStatus {
  worker_count: number;
  workers: WorkerInfo[];
  queues: Record<string, QueueInfo>;
}
