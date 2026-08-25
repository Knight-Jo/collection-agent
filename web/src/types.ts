export type Stage = "collect" | "assess" | "challenge" | "done";
export type RunStatus =
  | "queued"
  | "running"
  | "completed_sufficient"
  | "completed_with_gaps"
  | "failed"
  | "cancelled";

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

export type TrajectoryEventType =
  | "run_started"
  | "model_call"
  | "decision"
  | "action"
  | "observation"
  | "state_updated"
  | "run_finished";

export interface TrajectoryEnvelope {
  schema_version: string;
  run_id: string;
  task_id: string | null;
  event_id: string;
  sequence: number;
  parent_event_id: string | null;
  timestamp: string;
  layer: "technical" | "business" | "evaluation";
  event_type: TrajectoryEventType;
  origin: "model" | "deterministic" | "policy" | "human" | "system" | "tool";
  question_id: string | null;
  step_id: number | null;
  payload: Record<string, unknown>;
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
  browser: {
    enabled: boolean;
    playwright: boolean;
    chromium: boolean;
    network_mode: "validated" | "isolated";
  };
  processors: { tesseract: boolean; ffmpeg: boolean; whisper: boolean; libreoffice: boolean };
}

export interface CrawlResource {
  canonical_url: string;
  source_chain: string[];
  depth: number;
  status:
    | "queued"
    | "fetching"
    | "complete"
    | "reused"
    | "skipped_robots"
    | "skipped_http"
    | "skipped_limit"
    | "skipped_unsupported"
    | "failed";
  mime_type: string | null;
  size: number | null;
  downloaded_bytes: number;
  document_id: string | null;
  extraction: {
    status: "pending" | "complete" | "unavailable" | "failed" | "skipped";
    processor: string | null;
    text_path: string | null;
    error: string | null;
  };
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
    coverage: {
      status: string;
      answer_status?: "answered" | "partial" | "unanswered" | "conflicted";
      notes: string[];
    } | null;
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

export type MessageStatus = "accepted" | "processing" | "completed" | "failed" | "cancelled";

export interface MessageCitation {
  id: string;
  sequence: number;
  citation_kind: "verified_evidence" | "material_clue";
  title: string;
  source_url: string;
  quote_text: string;
  line_start: number;
  line_end: number;
}

export interface ConversationMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: MessageStatus;
  error?: string | null;
  citations: MessageCitation[];
}

export interface ConversationAction {
  id: string;
  action_type: string;
  immutable_payload: Record<string, unknown>;
  status:
    | "proposed"
    | "queued"
    | "executing"
    | "succeeded"
    | "failed"
    | "rejected"
    | "expired"
    | "cancelled";
  error: string | null;
}

export interface ResearchRun {
  id: string;
  task_id: string;
  active_search_plan_version_id: string | null;
  status:
    | "queued"
    | "running"
    | "stopping"
    | "stopped"
    | "succeeded"
    | "failed"
    | "cancelled"
    | "interrupted";
  phase: "planning" | "collecting" | "assessing" | "checkpointing" | null;
  error: string | null;
}

export interface ReportVersion {
  id: string;
  version: number;
  status: "draft" | "published" | "superseded" | "abandoned";
  content_path: string;
  based_on_checkpoint_id: string | null;
  based_on_committed_state_version: number;
  created_at: string;
}

export interface ConversationProjection {
  conversation: Conversation;
  epoch: { id: string; summary: string };
  messages: ConversationMessage[];
  actions: ConversationAction[];
  runs: ResearchRun[];
  reports: ReportVersion[];
  committed_state_version: number;
}

export interface Conversation {
  id: string;
  task_id: string | null;
  status: "intake" | "active" | "archived";
  title: string;
  active_epoch_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface TimelineEntry {
  id: string;
  conversation_id: string;
  timeline_sequence: number;
  source_event_sequence: number | null;
  entry_type: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface SearchPlanVersion {
  id: string;
  task_id: string;
  research_run_id: string;
  sequence: number;
  plan: Record<string, unknown>;
  created_at: string;
}
