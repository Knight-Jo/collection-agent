import type {
  AiSearchTool,
  Conversation,
  ConversationProjection,
  FactCheck,
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
import { httpGet, httpPatch, httpPost } from "@/api/http";
import {
  createFactCheck as dbCreateFactCheck,
  createMediaJob as dbCreateMediaJob,
  createMonitor as dbCreateMonitor,
  getFactCheck as dbGetFactCheck,
  getMediaJob as dbGetMediaJob,
  getMonitor as dbGetMonitor,
  listFactChecks as dbListFactChecks,
  listMediaJobs as dbListMediaJobs,
  listMonitors as dbListMonitors,
  runMonitorNow as dbRunMonitorNow,
  toggleMonitor as dbToggleMonitor,
} from "@/mocks/db";
import { simulateFactCheck, simulateMediaAnalysis } from "@/mocks/sse";

const LATENCY = 180;

async function wait<T>(value: T): Promise<T> {
  await new Promise((resolve) => setTimeout(resolve, LATENCY));
  return value;
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

  conversation: (
    id: string,
  ): Promise<ConversationProjection | undefined> =>
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

  library: (): Promise<Library> => httpGet<Library>("/library"),

  searchSources: (): Promise<SearchSource[]> =>
    httpGet<SearchSource[]>("/search-sources"),

  aiSearchTools: (): Promise<AiSearchTool[]> =>
    httpGet<AiSearchTool[]>("/ai-search-tools"),

  // --- monitors (mock) ---
  monitors: (): Promise<Monitor[]> => wait(dbListMonitors()),

  monitor: (id: string): Promise<MonitorDetail | undefined> =>
    wait(dbGetMonitor(id)),

  createMonitor: (input: {
    name: string;
    subject: string;
    strategy: string;
    frequency: string;
    questions: string[];
    websites: string[];
  }): Promise<Monitor> => wait(dbCreateMonitor(input)),

  toggleMonitor: (id: string): Promise<Monitor | undefined> =>
    wait(dbToggleMonitor(id)),

  runMonitorNow: (id: string): Promise<MonitorRun> =>
    wait(dbRunMonitorNow(id)),

  // --- fact checks (mock) ---
  factChecks: (): Promise<FactCheck[]> => wait(dbListFactChecks()),

  factCheck: (id: string): Promise<FactCheck | undefined> =>
    wait(dbGetFactCheck(id)),

  createFactCheck: (claim: string): Promise<FactCheck> => {
    const factCheck = dbCreateFactCheck(claim);
    void simulateFactCheck(factCheck.id);
    return wait(factCheck);
  },

  // --- search source / ai tool config (real backend) ---
  toggleSearchSource: (id: string): Promise<SearchSource | undefined> =>
    httpPost<SearchSource>(`/search-sources/${id}/toggle`),

  updateSearchSource: (
    id: string,
    patch: Partial<Pick<SearchSource, "cookies" | "enabled">>,
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

  // --- media jobs (mock) ---
  mediaJobs: (): Promise<MediaJob[]> => wait(dbListMediaJobs()),

  mediaJob: (id: string): Promise<MediaJob | undefined> =>
    wait(dbGetMediaJob(id)),

  createMediaJob: (input: {
    filename: string;
    kind: "audio" | "video";
    size: number;
  }): Promise<MediaJob> => {
    const job = dbCreateMediaJob(input);
    void simulateMediaAnalysis(job.id);
    return wait(job);
  },
};
