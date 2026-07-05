export type RetrievalRoute = "graph" | "vector" | "hybrid";
export type RetrievalType = RetrievalRoute | "deep_research";

export interface User {
  id: string;
  email: string;
  created_at: string;
}

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

export type ComparisonRow = string[];

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
  trust: TrustScore;
  subquestions: SubQuestionResult[];
  version: number;
  cached: boolean;
  created_at: string;
  // ── Conversation threading ──
  conversation_id?: string | null;
  turn_index?: number | null;
  // The rewritten, self-contained question the retrievers ran on. Present only
  // when the follow-up was condensed; null on first/standalone turns.
  standalone_question?: string | null;
}

// ── Deep Research (multi-agent orchestrator) ─────────────────────────────────

export interface SubQuestionResult {
  question: string;
  route: RetrievalRoute;
  why?: string;
  answer?: string;
  error?: string | null;
}

export interface TrustScore {
  // null when the answer had no checkable factual claims (vacuously grounded).
  score: number | null;
  supported: number;
  total: number;
  unsupported_claims: string[];
  claims?: { claim: string; supported: boolean }[];
}

export interface DeepResearchResult {
  id: string;
  question: string;
  answer: string;
  retrieval_type: "deep_research";
  subquestions: SubQuestionResult[];
  key_entities: KeyEntity[];
  conflicts: Conflict[];
  trust: TrustScore;
  version: number;
  created_at: string;
  conversation_id?: string | null;
}

// Live progress frame for one sub-agent while a deep-research run streams.
export interface SubAgentProgress {
  index: number;
  status: "running" | "done";
  question: string;
  route: RetrievalRoute;
  answer?: string;
  evidence?: { graph_records: number; passages: number; conflicts: number };
}

// ── Conversations ────────────────────────────────────────────────────────────

export interface ConversationSummary {
  id: string;
  title: string;
  turn_count: number;
  retrieval_type: RetrievalType | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail {
  id: string;
  workspace_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  turns: QuestionResponse[];
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

// Discovery: structural research gaps and generated conjectures.
export interface GapEntity {
  name: string;
  type: NodeType | string | null;
}

export interface GapEvidence {
  intermediary: GapEntity;
  source_relation_types: string[];
  target_relation_types: string[];
}

export interface ResearchGap {
  source: GapEntity;
  target: GapEntity;
  shared_intermediaries: GapEvidence[];
  score: number;
  common_neighbor_count: number;
  same_community: boolean;
  interdisciplinary: boolean;
  community_ids: { source: number | null; target: number | null };
  why_notable?: string | null;
}

export interface Hypothesis {
  source: GapEntity;
  target: GapEntity;
  statement: string;
  predicted_relationship_type: string;
  evidence: GapEvidence[];
  common_neighbor_count: number;
  same_community: boolean;
  interdisciplinary: boolean;
  confidence: "low" | "medium" | "high" | string;
  reasoning: string;
  caveat: string;
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

// ── Distributed worker pool (coordinator) status ─────────────────────────────

export interface CoordinatorWorker {
  worker_id: string;
  host: string;
  state: "idle" | "processing" | "dead";
  batch_id: string | null;
  completed: number;
  total: number;
  seconds_since_heartbeat: number;
}

export interface CoordinatorStatus {
  available: boolean;
  pending?: number;
  reassignments?: number;
  dead_workers?: number;
  heartbeat_timeout_secs?: number;
  worker_count?: number;
  live_worker_count?: number;
  workers?: CoordinatorWorker[];
}

// MCP "memory for other AI tools" setup config.

export interface McpClientInfo {
  key: string;
  label: string;
  config_path: string | null;
  path_scope: "global" | "workspace" | "project" | "";
  filename: string;
  docs: string;
  format: "mcpServers" | "vscode";
  config: Record<string, unknown>;
}

export interface McpConfig {
  workspace_id: string;
  workspace_name: string;
  server_name: string;
  mcp_installed: boolean;
  python: string;
  project_root: string;
  platform: string;
  docker_hosts: boolean;
  gemini_key_present: boolean;
  clients: McpClientInfo[];
}
