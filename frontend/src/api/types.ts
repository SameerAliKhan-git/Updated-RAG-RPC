export interface Citation {
  id: number;
  paper_title: string;
  authors: string[];
  arxiv_id: string;
  arxiv_url: string;
  pdf_url: string;
  section: string;
  snippet: string;
  page?: number | null;
  score?: number;
}

export interface VerificationIssue {
  claim: string;
  citation: string;
  issue: string;
  action: "remove" | "hedge" | "keep";
}

export interface Verification {
  verified_claims: number;
  total_claims: number;
  issues: VerificationIssue[];
}

export interface AskResult {
  answer_markdown: string;
  citations: Citation[];
  grounding_note: string;
  query_type: string;
  session_id: string;
  cached?: boolean;
  verification?: Verification | null;
}

export type StreamEvent =
  | { type: "trace"; step: string }
  | { type: "token"; text: string }
  | { type: "citation"; citation: Citation }
  | { type: "done"; result: AskResult }
  | { type: "error"; message: string };

export type ReadingStatus = "unread" | "to_read" | "reading" | "done";

export interface PaperSummary {
  arxiv_id: string;
  title: string;
  authors: string[];
  abstract: string;
  published_date: string;
  categories: string[];
  pdf_processed: boolean;
  chunk_count: number;
  reading_status: ReadingStatus;
  notes: string | null;
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
  verification?: Verification | null;
}

export interface ChatSession {
  id: string;
  title: string;
  createdAt: number;
}

export interface EvalHistoryEntry {
  timestamp: number;
  faithfulness: number;
  answer_relevancy: number;
  method?: string;
  dataset?: string;
  sample_count?: number;
}
