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
import { uid } from "@/lib/utils";
import {
  appendMessage,
  addSearchSource as dbAddSearchSource,
  createConversation as dbCreateConversation,
  createFactCheck as dbCreateFactCheck,
  createMediaJob as dbCreateMediaJob,
  createMonitor as dbCreateMonitor,
  generateBrief as dbGenerateBrief,
  getConversation as dbGetConversation,
  getFactCheck as dbGetFactCheck,
  getMediaJob as dbGetMediaJob,
  getMonitor as dbGetMonitor,
  listAiSearchTools as dbListAiSearchTools,
  listConversations as dbListConversations,
  listFactChecks as dbListFactChecks,
  listLibrary as dbListLibrary,
  listMediaJobs as dbListMediaJobs,
  listMonitors as dbListMonitors,
  listSearchSources as dbListSearchSources,
  runMonitorNow as dbRunMonitorNow,
  startResearchConversation as dbStartResearchConversation,
  systemStatus as dbSystemStatus,
  toggleAiSearchTool as dbToggleAiSearchTool,
  toggleMonitor as dbToggleMonitor,
  toggleSearchSource as dbToggleSearchSource,
  updateAiSearchToolApiKey as dbUpdateAiSearchToolApiKey,
  updateSearchSource as dbUpdateSearchSource,
  updateConversation,
} from "@/mocks/db";
import { simulateFactCheck, simulateMediaAnalysis, simulateReply } from "@/mocks/sse";

const LATENCY = 180;

async function wait<T>(value: T): Promise<T> {
  await new Promise((resolve) => setTimeout(resolve, LATENCY));
  return value;
}

export const api = {
  conversations: (archived = false): Promise<Conversation[]> => wait(dbListConversations(archived)),

  createConversation: (): Promise<Conversation> => wait(dbCreateConversation()),

  archiveConversation: (id: string): Promise<Conversation | undefined> =>
    wait(updateConversation(id, { status: "archived" })),

  restoreConversation: (id: string): Promise<Conversation | undefined> =>
    wait(updateConversation(id, { status: "active" })),

  conversation: (id: string): Promise<ConversationProjection | undefined> =>
    wait(dbGetConversation(id)),

  sendMessage: (id: string, content: string): Promise<Message> => {
    const message: Message = {
      id: uid(),
      role: "user",
      content,
      status: "completed",
      citations: [],
    };
    appendMessage(id, message);
    void simulateReply(id, content);
    return wait(message);
  },

  monitors: (): Promise<Monitor[]> => wait(dbListMonitors()),

  monitor: (id: string): Promise<MonitorDetail | undefined> => wait(dbGetMonitor(id)),

  createMonitor: (input: {
    name: string;
    subject: string;
    strategy: string;
    frequency: string;
    questions: string[];
    websites: string[];
  }): Promise<Monitor> => wait(dbCreateMonitor(input)),

  toggleMonitor: (id: string): Promise<Monitor | undefined> => wait(dbToggleMonitor(id)),

  runMonitorNow: (id: string): Promise<MonitorRun> => wait(dbRunMonitorNow(id)),

  factChecks: (): Promise<FactCheck[]> => wait(dbListFactChecks()),

  factCheck: (id: string): Promise<FactCheck | undefined> => wait(dbGetFactCheck(id)),

  createFactCheck: (claim: string): Promise<FactCheck> => {
    const factCheck = dbCreateFactCheck(claim);
    void simulateFactCheck(factCheck.id);
    return wait(factCheck);
  },

  generateBrief: (prompt: string): Promise<ResearchBrief> => wait(dbGenerateBrief(prompt)),

  startResearch: (topic: string, brief: ResearchBrief): Promise<Conversation> =>
    wait(dbStartResearchConversation(topic, brief)),

  system: (): Promise<SystemStatus> => wait(dbSystemStatus()),

  library: (): Promise<Library> => wait(dbListLibrary()),

  searchSources: (): Promise<SearchSource[]> => wait(dbListSearchSources()),

  toggleSearchSource: (id: string): Promise<SearchSource | undefined> =>
    wait(dbToggleSearchSource(id)),

  updateSearchSource: (
    id: string,
    patch: Partial<Pick<SearchSource, "cookies" | "enabled">>,
  ): Promise<SearchSource | undefined> => wait(dbUpdateSearchSource(id, patch)),

  addSearchSource: (input: { name: string; url: string }): Promise<SearchSource> =>
    wait(dbAddSearchSource(input)),

  aiSearchTools: (): Promise<AiSearchTool[]> => wait(dbListAiSearchTools()),

  toggleAiSearchTool: (id: string): Promise<AiSearchTool | undefined> =>
    wait(dbToggleAiSearchTool(id)),

  updateAiSearchToolApiKey: (id: string, apiKey: string): Promise<AiSearchTool | undefined> =>
    wait(dbUpdateAiSearchToolApiKey(id, apiKey)),

  mediaJobs: (): Promise<MediaJob[]> => wait(dbListMediaJobs()),

  mediaJob: (id: string): Promise<MediaJob | undefined> => wait(dbGetMediaJob(id)),

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
