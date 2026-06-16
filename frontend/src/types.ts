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

export interface QuestionResponse {
  id: string;
  question: string;
  answer: string;
  retrieval_type: RetrievalType;
  reasoning: string;
  cypher: string | null;
  graph_records: GraphRecord[];
  vector_chunks: VectorChunk[];
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
