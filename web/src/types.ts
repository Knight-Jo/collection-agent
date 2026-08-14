export type Stage = "collect" | "assess" | "challenge" | "done";
export type RunStatus = "queued" | "running" | "completed_sufficient" | "completed_with_gaps" | "failed" | "cancelled";

export interface Criteria {
  min_independent_sources: number;
  min_high_quality_sources: number;
  recency_days: number;
  require_recency: boolean;
}

export interface RunInput {
  topic: string;
  objective?: string;
  questions?: string[];
  scope?: { time_range: string; geography: string[]; languages: string[] };
  report_depth?: "brief" | "standard" | "deep";
  deep_crawl: boolean | null;
  criteria: Criteria;
}

export interface Run {
  run_id: string;
  status: RunStatus;
  task_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  result: string | null;
  error: { code: string; message: string } | null;
}

export interface RunEvent {
  id: number;
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
}

export interface TaskSummary {
  id: string;
  topic: string;
  stage: Stage;
  updated_at: string;
  coverage_level: string | null;
  gap_score: number | null;
  evidence_count: number;
}

export interface SystemStatus {
  model: { name: string; configured: boolean };
  audit: { name: string; configured: boolean };
  search: { name: string; configured: boolean };
  crawl: { default_enabled: boolean };
  processors: { tesseract: boolean; ffmpeg: boolean; whisper: boolean; libreoffice: boolean };
}

export interface CrawlResource {
  canonical_url: string;
  source_chain: string[];
  depth: number;
  status: "queued" | "fetching" | "complete" | "reused" | "skipped_robots" | "skipped_http" | "skipped_limit" | "skipped_unsupported" | "failed";
  mime_type: string | null;
  size: number | null;
  downloaded_bytes: number;
  document_id: string | null;
  extraction: { status: "pending" | "complete" | "unavailable" | "failed" | "skipped"; processor: string | null; text_path: string | null; error: string | null };
  error: string | null;
  rating: number | null;
  description: string | null;
}

export interface MaterialDigest {
  overview: string;
  key_points: string[];
  priority_materials: string[];
  reading_guide: Record<string, string[]>;
  gaps: string[];
}

export interface Evidence {
  id: string;
  relation: "supports" | "contradicts";
  quote: string;
  line_start: number;
  line_end: number;
  notes: string;
  document: {
    title: string;
    final_url: string;
    source_type: string;
    source_group: string;
    publish_time: string | null;
    injection_warnings: string[];
  };
  review: { verdict: string; reason: string } | null;
}

export interface Fact {
  id: string;
  statement: string;
  status: string;
  coverage: { status: string; gap_score: number; notes: string[] } | null;
  evidence: Evidence[];
}

export interface TaskDetail {
  task: {
    id: string;
    topic: string;
    stage: Stage;
    updated_at: string;
    criteria: Criteria;
    outputs: { report: unknown | null; assessment: unknown | null; package: unknown | null };
  };
  coverage: {
    level: string;
    gap_score: number;
    stop_reason: string | null;
  } | null;
  questions: Array<{
    id: string;
    text: string;
    coverage: { status: string; notes: string[] } | null;
    facts: Fact[];
  }>;
  conflicts: Array<{ id: string; resolution: string; note: string }>;
  challenges: Array<{
    id: string;
    round: number;
    status: string;
    points: Array<{ id: string; challenge: string; status: string }>;
  }>;
  resources: CrawlResource[];
  material_digest: MaterialDigest | null;
}

export interface Artifact {
  kind: "report" | "assessment" | "package";
  path: string;
  content: string;
  content_sha256: string;
}
