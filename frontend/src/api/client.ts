import type {
  AiSearchTool,
  Conversation,
  ConversationProjection,
  FactCheck,
  FactEvidence,
  Library,
  MediaJob,
  Message,
  Monitor,
  MonitorDetail,
  MonitorRun,
  ResearchBrief,
  SearchSource,
  SystemStatus,
} from "@/api/types";
import { errorMessage, httpGet, httpPatch, httpPost } from "@/api/http";

type Schedule = {
  cadence: "daily" | "weekly";
  local_time: string;
  timezone: string;
  weekday?: number | null;
};

const WEEKDAYS = ["日", "一", "二", "三", "四", "五", "六"];

function scheduleToFrequency(schedule: Schedule): string {
  const time = schedule?.local_time ?? "09:00";
  if (schedule?.cadence === "weekly") {
    const weekday = schedule.weekday ?? 0;
    return `每周${WEEKDAYS[weekday]} ${time}`;
  }
  return `每天 ${time}`;
}

function parseSchedule(frequency: string): Schedule {
  const match = frequency.match(/(\d{2}):(\d{2})/);
  const time = match ? `${match[1]}:${match[2]}` : "09:00";
  if (frequency.startsWith("每周")) {
    const dayChar = frequency.slice(2, 3);
    const weekday = WEEKDAYS.indexOf(dayChar);
    return {
      cadence: "weekly",
      local_time: time,
      timezone: "UTC",
      weekday: weekday >= 0 ? weekday : 0,
    };
  }
  return { cadence: "daily", local_time: time, timezone: "UTC" };
}

function mapMonitor(raw: Record<string, unknown>): Monitor {
  return {
    id: String(raw.monitor_id ?? ""),
    name: String(raw.name ?? ""),
    subject: String(raw.subject ?? ""),
    strategy: String(raw.strategy ?? ""),
    frequency: scheduleToFrequency(raw.schedule as Schedule),
    status: (raw.status as "active" | "paused") ?? "active",
    next_run_at: (raw.next_run_at as string | null) ?? null,
    last_run_at: (raw.last_run_at as string | null) ?? null,
    created_at: String(raw.created_at ?? ""),
    questions: (raw.questions as string[]) ?? [],
    websites: (raw.websites as string[]) ?? [],
  };
}

function mapMonitorRun(raw: Record<string, unknown>): MonitorRun {
  const run = (raw.run ?? {}) as Record<string, unknown>;
  return {
    id: String(run.run_id ?? ""),
    monitor_id: String(run.monitor_id ?? ""),
    status: (raw.status as MonitorRun["status"]) ?? "succeeded",
    started_at: (raw.started_at as string | null) ?? null,
    finished_at: (raw.finished_at as string | null) ?? null,
    changes: ((raw.changes as Record<string, unknown>[]) ?? []).map((c) => ({
      id: String(c.change_id ?? ""),
      kind: (c.kind as MonitorRun["changes"][number]["kind"]) ?? "new_fact",
      importance: (c.importance as "high" | "normal") ?? "normal",
      summary: String(c.summary ?? ""),
      at: String(c.created_at ?? ""),
    })),
    summary: String(run.summary ?? ""),
  };
}

function mapMonitorDetail(raw: Record<string, unknown>): MonitorDetail {
  return {
    monitor: mapMonitor((raw.monitor ?? {}) as Record<string, unknown>),
    runs: ((raw.runs as Record<string, unknown>[]) ?? []).map(mapMonitorRun),
  };
}

function mapFactEvidence(raw: Record<string, unknown>): FactEvidence {
  const citation = (raw.citation ?? {}) as Record<string, unknown>;
  return {
    id: String(raw.evidence_id ?? ""),
    relation: (raw.relation as "supports" | "contradicts") ?? "supports",
    quote: String(raw.quote ?? ""),
    source_title: String(raw.source_title ?? ""),
    source_url: String(citation.source_url ?? ""),
  };
}

function mapFactCheck(raw: Record<string, unknown>): FactCheck {
  const fc = (raw.fact_check ?? raw) as Record<string, unknown>;
  return {
    id: String(fc.fact_check_id ?? ""),
    claim: String(fc.claim ?? ""),
    understanding: String(fc.understanding ?? ""),
    questions: (fc.questions as string[]) ?? [],
    status: (raw.status as "running" | "completed") ?? "running",
    verdict: (fc.verdict as FactCheck["verdict"]) ?? null,
    evidence_sufficiency:
      (fc.evidence_sufficiency as FactCheck["evidence_sufficiency"]) ?? null,
    independent_sources: Number(fc.independent_sources ?? 0),
    primary_sources: Number(fc.primary_sources ?? 0),
    counter_evidence: Number(fc.counter_evidence ?? 0),
    evidence: ((raw.evidence as Record<string, unknown>[]) ?? []).map(
      mapFactEvidence,
    ),
    timeline: ((raw.timeline as Record<string, unknown>[]) ?? []).map((step) => ({
      id: String(step.entry_id ?? ""),
      phase: String(step.phase ?? ""),
      state: String(step.state ?? ""),
      summary: String(step.summary ?? ""),
      at: String(step.created_at ?? ""),
    })),
    created_at: String(raw.created_at ?? fc.created_at ?? ""),
    checkability:
      (fc.checkability as FactCheck["checkability"]) ?? "pending",
    checkability_reason: (fc.checkability_reason as string | null) ?? null,
    rationale: String(fc.rationale ?? ""),
    limitations: (fc.limitations as string[]) ?? [],
  };
}

function mapMediaJob(raw: Record<string, unknown>): MediaJob {
  const job = (raw.job ?? raw) as Record<string, unknown>;
  return {
    id: String(job.media_job_id ?? ""),
    filename: String(job.filename ?? ""),
    kind: (job.kind as "audio" | "video") ?? "audio",
    size: Number(job.size_bytes ?? 0),
    status: (raw.status as MediaJob["status"]) ?? "transcribing",
    segments: ((raw.segments as Record<string, unknown>[]) ?? []).map((s) => {
      const loc = (s.locator ?? {}) as Record<string, unknown>;
      return {
        id: String(s.segment_id ?? ""),
        start: Number(loc.start_ms ?? 0),
        end: Number(loc.end_ms ?? 0),
        text: String(s.text ?? ""),
        speaker: (s.speaker as string | null) ?? null,
      };
    }),
    facts: ((raw.facts as Record<string, unknown>[]) ?? []).map((f) => ({
      id: String(f.fact_id ?? ""),
      statement: String(f.statement ?? ""),
      segment_id: String((f.segment_ids as string[])?.[0] ?? ""),
      status: "unverified",
    })),
    evidence: ((raw.evidence as Record<string, unknown>[]) ?? []).map((e) => {
      const loc = (e.locator ?? {}) as Record<string, unknown>;
      return {
        id: String(e.evidence_id ?? ""),
        relation: (e.relation as MediaJob["evidence"][number]["relation"]) ?? "mentions",
        quote: String(e.quote ?? ""),
        start: Number(loc.start_ms ?? 0),
        end: Number(loc.end_ms ?? 0),
      };
    }),
    summary: (job.summary as string | null) ?? null,
    created_at: String(job.created_at ?? ""),
  };
}

export const api = {
  // --- research loop (real backend) ---
  conversations: (archived = false): Promise<Conversation[]> =>
    httpGet<Conversation[]>(`/conversations?archived=${archived}`),

  createConversation: (): Promise<Conversation> =>
    httpPost<Conversation>("/conversations"),

  archiveConversation: (id: string): Promise<Conversation | undefined> =>
    httpPost<Conversation>(`/conversations/${id}/archive`),

  restoreConversation: (id: string): Promise<Conversation | undefined> =>
    httpPost<Conversation>(`/conversations/${id}/restore`),

  conversation: (id: string): Promise<ConversationProjection | undefined> =>
    httpGet<ConversationProjection>(`/conversations/${id}`),

  sendMessage: (id: string, content: string): Promise<Message> =>
    httpPost<Message>(`/conversations/${id}/messages`, { content }),

  generateBrief: (prompt: string): Promise<ResearchBrief> =>
    httpPost<ResearchBrief>("/briefs/generate", { prompt }),

  startResearch: (
    topic: string,
    brief: ResearchBrief,
  ): Promise<Conversation> =>
    httpPost<Conversation>("/research/start", { topic, brief }),

  system: (): Promise<SystemStatus> => httpGet<SystemStatus>("/system"),

  library: async (): Promise<Library> => {
    const raw = await httpGet<{
      research: Library["research"];
      monitors: Record<string, unknown>[];
      factChecks: Record<string, unknown>[];
      media: Record<string, unknown>[];
    }>("/library");
    return {
      research: raw.research,
      monitors: raw.monitors.map(mapMonitorDetail),
      factChecks: raw.factChecks.map(mapFactCheck),
      media: raw.media.map(mapMediaJob),
    };
  },

  searchSources: (): Promise<SearchSource[]> =>
    httpGet<SearchSource[]>("/search-sources"),

  aiSearchTools: (): Promise<AiSearchTool[]> =>
    httpGet<AiSearchTool[]>("/ai-search-tools"),

  // --- monitors (real backend) ---
  monitors: async (): Promise<Monitor[]> => {
    const raw = await httpGet<Record<string, unknown>[]>("/monitors");
    return raw.map(mapMonitor);
  },

  monitor: async (id: string): Promise<MonitorDetail | undefined> => {
    const raw = await httpGet<Record<string, unknown>>(`/monitors/${id}`);
    return mapMonitorDetail(raw);
  },

  createMonitor: async (input: {
    name: string;
    subject: string;
    strategy: string;
    frequency: string;
    questions: string[];
    websites: string[];
  }): Promise<Monitor> => {
    const raw = await httpPost<Record<string, unknown>>("/monitors", {
      name: input.name,
      subject: input.subject,
      strategy: input.strategy,
      schedule: parseSchedule(input.frequency),
      questions: input.questions,
      websites: input.websites,
    });
    return mapMonitor(raw);
  },

  toggleMonitor: async (id: string): Promise<Monitor | undefined> => {
    const raw = await httpPost<Record<string, unknown>>(
      `/monitors/${id}/toggle`,
    );
    return mapMonitor(raw);
  },

  runMonitorNow: async (id: string): Promise<MonitorRun> => {
    const raw = await httpPost<Record<string, unknown>>(
      `/monitors/${id}/runs`,
      { trigger: "manual" },
    );
    return mapMonitorRun(raw);
  },

  // --- fact checks (real backend) ---
  factChecks: async (): Promise<FactCheck[]> => {
    const raw = await httpGet<Record<string, unknown>[]>("/fact-checks");
    return raw.map(mapFactCheck);
  },

  factCheck: async (id: string): Promise<FactCheck | undefined> => {
    const raw = await httpGet<Record<string, unknown>>(`/fact-checks/${id}`);
    return mapFactCheck(raw);
  },

  createFactCheck: async (claim: string): Promise<FactCheck> => {
    const raw = await httpPost<Record<string, unknown>>("/fact-checks", {
      claim,
    });
    return mapFactCheck(raw);
  },

  // --- search source / ai tool config (real backend) ---
  toggleSearchSource: (id: string): Promise<SearchSource | undefined> =>
    httpPost<SearchSource>(`/search-sources/${id}/toggle`),

  updateSearchSource: (
    id: string,
    patch: Partial<Pick<SearchSource, "enabled">> & { cookies?: string },
  ): Promise<SearchSource | undefined> =>
    httpPatch<SearchSource>(`/search-sources/${id}`, patch),

  addSearchSource: (input: {
    name: string;
    url: string;
  }): Promise<SearchSource> => httpPost<SearchSource>("/search-sources", input),

  toggleAiSearchTool: (id: string): Promise<AiSearchTool | undefined> =>
    httpPost<AiSearchTool>(`/ai-search-tools/${id}/toggle`),

  updateAiSearchToolApiKey: (
    id: string,
    apiKey: string,
  ): Promise<AiSearchTool | undefined> =>
    httpPatch<AiSearchTool>(`/ai-search-tools/${id}/api-key`, {
      api_key: apiKey,
    }),

  // --- media jobs (real backend) ---
  mediaJobs: async (): Promise<MediaJob[]> => {
    const raw = await httpGet<Record<string, unknown>[]>("/media");
    return raw.map(mapMediaJob);
  },

  mediaJob: async (id: string): Promise<MediaJob | undefined> => {
    const raw = await httpGet<Record<string, unknown>>(`/media/${id}`);
    return mapMediaJob(raw);
  },

  createMediaJob: async (input: {
    file: File;
  }): Promise<MediaJob> => {
    const form = new FormData();
    form.append("file", input.file);
    const response = await fetch("/api/media", {
      method: "POST",
      body: form,
    });
    if (!response.ok) {
      throw new Error(await errorMessage(response));
    }
    const raw = (await response.json()) as Record<string, unknown>;
    return mapMediaJob(raw);
  },
};
