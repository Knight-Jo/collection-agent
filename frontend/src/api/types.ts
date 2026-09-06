export type RunStatus = "queued" | "running" | "stopping" | "stopped" | "succeeded" | "failed";export type RunPhase = "planning" | "collecting" | "assessing" | "checkpointing";

export interface Conversation {
  id: string;
  title: string;
  status: "intake" | "active" | "archived";
  updated_at: string;
  run_status: RunStatus | null;
  run_phase: RunPhase | null;
}

export interface MessageCitation {
  id: string;
  sequence: number;
  title: string;
  source_url: string;
  quote_text: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "accepted" | "processing" | "completed";
  citations: MessageCitation[];
}

export interface Material {
  id: string;
  title: string;
  url: string;
  source_type: string;
  rating: number;
  description: string;
  download_url?: string;
}

export interface Run {
  id: string;
  status: RunStatus;
  phase: RunPhase | null;
}

export type TimelineKind =
  | "intent"
  | "search_plan"
  | "search"
  | "material"
  | "evidence"
  | "coverage"
  | "decision"
  | "report";

export interface TimelineEntry {
  id: string;
  kind: TimelineKind;
  label: string;
  detail?: string;
  at: string;
}

export interface ConversationProjection {
  conversation: Conversation;
  messages: Message[];
  run: Run | null;
  materials: Material[];
  timeline: TimelineEntry[];
  committed_state_version: number;
  report_ready: boolean;
  brief: ResearchBrief | null;
  questions: ResearchQuestion[];
  gaps: ResearchGap[];
}

export type AgentEvent =
  | { type: "answer.started" }
  | { type: "answer.delta"; delta: string }
  | { type: "answer.completed" }
  | { type: "run.status"; status: RunStatus }
  | { type: "run.phase"; phase: RunPhase }
  | { type: "timeline"; entry: TimelineEntry }
  | { type: "material"; material: Material }
  | { type: "refetch" };

export interface Monitor {
  id: string;
  name: string;
  subject: string;
  strategy: string;
  frequency: string;
  status: "active" | "paused";
  next_run_at: string | null;
  last_run_at: string | null;
  created_at: string;
  questions: string[];
  websites: string[];
}

export type MonitorRunStatus = "running" | "succeeded" | "failed";

export type MonitorChangeKind = "new_fact" | "changed_fact" | "new_source";

export interface MonitorChange {
  id: string;
  kind: MonitorChangeKind;
  importance: "high" | "normal";
  summary: string;
  at: string;
}

export interface MonitorRun {
  id: string;
  monitor_id: string;
  status: MonitorRunStatus;
  started_at: string | null;
  finished_at: string | null;
  changes: MonitorChange[];
  summary: string;
}

export interface MonitorDetail {
  monitor: Monitor;
  runs: MonitorRun[];
}

export type Verdict =
  | "supported"
  | "mostly_supported"
  | "insufficient"
  | "disputed"
  | "mostly_refuted"
  | "refuted";

export type EvidenceSufficiency = "high" | "medium" | "low";

export type Checkability = "pending" | "checkable" | "not_checkable";

export interface FactCheckStep {
  id: string;
  phase: string;
  state: string;
  summary: string;
  at: string;
}

export interface FactEvidence {
  id: string;
  relation: "supports" | "contradicts";
  quote: string;
  source_title: string;
  source_url: string;
}

export interface FactCheck {
  id: string;
  claim: string;
  understanding: string;
  questions: string[];
  status: "running" | "completed";
  verdict: Verdict | null;
  evidence_sufficiency: EvidenceSufficiency | null;
  independent_sources: number;
  primary_sources: number;
  counter_evidence: number;
  evidence: FactEvidence[];
  timeline: FactCheckStep[];
  created_at: string;
  checkability: Checkability;
  checkability_reason: string | null;
  rationale: string;
  limitations: string[];
}

export interface ResearchBrief {
  goal: string;
  scope: string;
  questions: string[];
  key_entities: string[];
  suggested_sources: string[];
}

export interface ResearchQuestion {
  id: string;
  text: string;
  status: "pending" | "researching" | "answered" | "blocked";
  evidence_count: number;
  coverage_note: string;
}

export interface ResearchGap {
  id: string;
  question_id: string;
  reason: string;
}

export interface SystemStatus {
  model: { name: string; configured: boolean };
  search: { name: string; configured: boolean };
  processors: { tesseract: boolean; ffmpeg: boolean; whisper: boolean };
}

export interface LibraryFact {
  id: string;
  statement: string;
  status: string;
  updated_at: string;
}

export interface LibrarySource {
  id: string;
  name: string;
  type: string;
  url: string;
}

export interface SearchSource {
  id: string;
  name: string;
  url: string;
  enabled: boolean;
  cookie_configured: boolean;
  executable?: boolean;
}

export interface AiSearchTool {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  api_key_configured: boolean;
  api_key_env: string;
}

export interface Report {
  id: string;
  version: number;
  status: "draft" | "published";
  content: string;
  created_at: string;
}

export interface LibraryTask {
  id: string;
  title: string;
  updated_at: string;
  materials: Material[];
  facts: LibraryFact[];
  evidence: FactEvidence[];
  sources: LibrarySource[];
  report: Report | null;
}

export interface LibraryResearchRecord extends LibraryTask {
  brief: ResearchBrief | null;
  questions: ResearchQuestion[];
  timeline: TimelineEntry[];
}

export interface Library {
  research: LibraryResearchRecord[];
  monitors: MonitorDetail[];
  factChecks: FactCheck[];
  media: MediaJob[];
}

export type MediaKind = "audio" | "video";

export type MediaJobStatus = "transcribing" | "analyzing" | "completed" | "failed";

export interface MediaSegment {
  id: string;
  start: number;
  end: number;
  text: string;
  speaker: string | null;
}

export interface MediaFact {
  id: string;
  statement: string;
  segment_id: string;
  status: string;
}

export interface MediaEvidence {
  id: string;
  relation: "supports" | "contradicts";
  quote: string;
  start: number;
  end: number;
}

export interface MediaJob {
  id: string;
  filename: string;
  kind: MediaKind;
  size: number;
  status: MediaJobStatus;
  segments: MediaSegment[];
  facts: MediaFact[];
  evidence: MediaEvidence[];
  summary: string | null;
  created_at: string;
}
