export interface Citation {
  id: number;
  paper_title: string;
  authors: string[];
  arxiv_id: string;
  arxiv_url: string;
  pdf_url: string;
  section: string;
  snippet: string;
}

export interface AskResult {
  answer_markdown: string;
  citations: Citation[];
  grounding_note: string;
  query_type: string;
  session_id: string;
  cached?: boolean;
}

export type StreamEvent =
  | { type: "trace"; step: string }
  | { type: "token"; text: string }
  | { type: "citation"; citation: Citation }
  | { type: "done"; result: AskResult }
  | { type: "error"; message: string };

export interface PaperSummary {
  arxiv_id: string;
  title: string;
  authors: string[];
  abstract: string;
  published_date: string;
  categories: string[];
  pdf_processed: boolean;
  chunk_count: number;
}

export interface PaperListResponse {
  papers: PaperSummary[];
  total: number;
  page: number;
  per_page: number;
}

export interface HealthStatus {
  status: string;
  services?: Record<string, { status: string; latency_ms?: number }>;
  [key: string]: unknown;
}

export interface EvalStatus {
  status: string;
  timestamp: string | null;
  scores: {
    faithfulness?: number;
    answer_relevancy?: number;
    method?: string;
    dataset?: string;
    sample_count?: number;
  } | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  groundingNote?: string;
  cached?: boolean;
  streaming?: boolean;
}

export interface ChatSession {
  id: string;
  title: string;
  createdAt: number;
}
