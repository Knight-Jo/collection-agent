import type {
  AiSearchTool,
  Conversation,
  ConversationProjection,
  FactCheck,
  FactEvidence,
  Library,
  LibraryFact,
  LibraryResearchRecord,
  LibrarySource,
  Material,
  MediaEvidence,
  MediaFact,
  MediaJob,
  MediaSegment,
  Message,
  Monitor,
  MonitorDetail,
  MonitorRun,
  Report,
  ResearchBrief,
  ResearchGap,
  ResearchQuestion,
  SearchSource,
  SystemStatus,
  TimelineEntry,
} from "@/api/types";
import { uid } from "@/lib/utils";

function iso(offsetMinutes: number): string {
  return new Date(Date.now() - offsetMinutes * 60_000).toISOString();
}

function future(offsetMinutes: number): string {
  return new Date(Date.now() + offsetMinutes * 60_000).toISOString();
}

function now(): string {
  return new Date().toISOString();
}

function projection(
  conversation: Conversation,
  messages: Message[],
  timeline: TimelineEntry[],
  materials: Material[],
  brief: ResearchBrief | null = null,
  questions: ResearchQuestion[] = [],
  gaps: ResearchGap[] = [],
): ConversationProjection {
  return {
    conversation,
    messages,
    run:
      conversation.run_status === null
        ? null
        : {
            id: `run-${conversation.id}`,
            status: conversation.run_status,
            phase: conversation.run_phase,
          },
    materials,
    timeline,
    committed_state_version: messages.length,
    report_ready: conversation.run_status === "succeeded",
    brief,
    questions,
    gaps,
  };
}

const seedMessages = (conversationId: string, user: string, assistant: string): Message[] => [
  {
    id: `${conversationId}-m1`,
    role: "user",
    content: user,
    status: "completed",
    citations: [],
  },
  {
    id: `${conversationId}-m2`,
    role: "assistant",
    content: assistant,
    status: "completed",
    citations: [
      {
        id: `${conversationId}-c1`,
        sequence: 1,
        title: "中国先进封装产业白皮书 2026",
        source_url: "https://example.com/advanced-packaging-2026",
        quote_text: "2025 年国内先进封装市场规模约 850 亿元，同比增长 21%。",
      },
    ],
  },
];

const seedMaterials = (conversationId: string): Material[] => [
  {
    id: `${conversationId}-doc1`,
    title: "中国先进封装产业白皮书 2026",
    url: "https://example.com/advanced-packaging-2026",
    source_type: "行业报告",
    rating: 5,
    description: "权威行业白皮书，覆盖市场规模、竞争格局与技术路线。",
  },
  {
    id: `${conversationId}-doc2`,
    title: "长电科技 2025 年报",
    url: "https://example.com/jcet-annual",
    source_type: "企业披露",
    rating: 4,
    description: "封装龙头财报，含产能与客户结构数据。",
  },
  {
    id: `${conversationId}-doc3`,
    title: "AI 芯片对 CoWoS 产能的需求分析",
    url: "https://example.com/cowos-demand",
    source_type: "研究文章",
    rating: 3,
    description: "第三方分析，观点为主，数据口径需交叉验证。",
  },
];

const seedTimeline = (conversationId: string): TimelineEntry[] => [
  {
    id: `${conversationId}-t1`,
    kind: "intent",
    label: "理解调研目标",
    detail: "拆解为 3 个关键问题：市场规模、主要玩家、技术路线",
    at: iso(62),
  },
  {
    id: `${conversationId}-t2`,
    kind: "search_plan",
    label: "生成检索计划",
    detail: "12 组检索方向，覆盖产业报告、企业披露与学术来源",
    at: iso(61),
  },
  {
    id: `${conversationId}-t3`,
    kind: "search",
    label: "执行检索",
    detail: "SearXNG 命中 27 个来源，去重后保留 12 个",
    at: iso(60),
  },
  {
    id: `${conversationId}-t4`,
    kind: "material",
    label: "材料入库",
    detail: "抓取并提取 9 份文档",
    at: iso(58),
  },
  {
    id: `${conversationId}-t5`,
    kind: "evidence",
    label: "证据核验",
    detail: "提取 18 条证据，覆盖 3 个关键问题",
    at: iso(55),
  },
  {
    id: `${conversationId}-t6`,
    kind: "coverage",
    label: "覆盖率评估",
    detail: "覆盖率 89%，缺口：细分封装工艺良率数据",
    at: iso(50),
  },
];

const done = (
  id: string,
  title: string,
  user: string,
  assistant: string,
): ConversationProjection => {
  const conversation: Conversation = {
    id,
    title,
    status: "active",
    updated_at: iso(50),
    run_status: "succeeded",
    run_phase: "checkpointing",
  };
  return projection(
    conversation,
    seedMessages(id, user, assistant),
    seedTimeline(id),
    seedMaterials(id),
    seedBrief(),
    seedQuestions(id, true),
    seedGaps(id),
  );
};

const running = (id: string, title: string, user: string): ConversationProjection => {
  const conversation: Conversation = {
    id,
    title,
    status: "active",
    updated_at: iso(1),
    run_status: "running",
    run_phase: "collecting",
  };
  return projection(
    conversation,
    [{ id: `${id}-m1`, role: "user", content: user, status: "completed", citations: [] }],
    [
      {
        id: `${id}-t1`,
        kind: "intent",
        label: "理解调研目标",
        at: iso(1),
      },
      {
        id: `${id}-t2`,
        kind: "search_plan",
        label: "生成检索计划",
        at: iso(0),
      },
    ],
    seedMaterials(id).slice(0, 1),
    seedBrief(),
    seedQuestions(id, false),
    seedGaps(id),
  );
};

function seedBrief(): ResearchBrief {
  return {
    goal: "梳理该主题的竞争格局、主要玩家与关键变化",
    scope: "公开信息为主，覆盖企业披露、行业报告与第三方研究",
    questions: ["市场规模与格局", "主要玩家份额", "技术路线与产能"],
    key_entities: ["长电科技", "通富微电", "华天科技"],
    suggested_sources: ["行业白皮书", "企业年报", "第三方研究"],
  };
}

function seedQuestions(id: string, isDone: boolean): ResearchQuestion[] {
  return [
    {
      id: `${id}-q1`,
      text: "市场规模与格局",
      status: "answered",
      evidence_count: 6,
      coverage_note: "覆盖充分",
    },
    {
      id: `${id}-q2`,
      text: "主要玩家份额",
      status: isDone ? "answered" : "researching",
      evidence_count: 4,
      coverage_note: "覆盖充分",
    },
    {
      id: `${id}-q3`,
      text: "细分工艺良率",
      status: isDone ? "blocked" : "pending",
      evidence_count: 0,
      coverage_note: "仅有厂商二手材料，缺乏独立来源",
    },
  ];
}

function seedGaps(id: string): ResearchGap[] {
  return [
    {
      id: `${id}-g1`,
      question_id: `${id}-q3`,
      reason: "细分封装工艺良率缺乏独立来源，仅有厂商二手材料",
    },
  ];
}

const seed: Record<string, ConversationProjection> = {
  "conv-1": done(
    "conv-1",
    "先进封装产业竞争格局",
    "调研中国先进封装产业的竞争格局，重点关注主要厂商与市场份额。",
    "已完成调研。国内先进封装市场高度集中于长电科技、通富微电、华天科技三家，合计份额约 38%；高端 CoWoS 产能仍由台积电主导。",
  ),
  "conv-2": done(
    "conv-2",
    "AI 芯片供应链风险",
    "分析 AI 训练芯片供应链的关键瓶颈与国产替代进展。",
    "关键瓶颈集中在 HBM 与先进制程产能。国产替代在封测环节进展最快，长电、通富已进入头部客户供应链。",
  ),
  "conv-3": running(
    "conv-3",
    "碳化硅功率器件产能",
    "调研国内碳化硅功率器件的最新产能建设与良率情况。",
  ),
};

export function listConversations(archived: boolean): Conversation[] {
  return Object.values(seed)
    .filter((item) =>
      archived ? item.conversation.status === "archived" : item.conversation.status !== "archived",
    )
    .map((item) => item.conversation)
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

export function getConversation(id: string): ConversationProjection | undefined {
  return seed[id];
}

export function createConversation(): Conversation {
  const id = `conv-${uid().slice(0, 8)}`;
  const conversation: Conversation = {
    id,
    title: "新建调研",
    status: "intake",
    updated_at: new Date().toISOString(),
    run_status: null,
    run_phase: null,
  };
  seed[id] = projection(conversation, [], [], []);
  return conversation;
}

export function updateConversation(
  id: string,
  patch: Partial<Conversation>,
): Conversation | undefined {
  const current = seed[id];
  if (!current) return undefined;
  current.conversation = { ...current.conversation, ...patch };
  return current.conversation;
}

export function appendMessage(id: string, message: Message): void {
  seed[id]?.messages.push(message);
  if (seed[id]) seed[id].conversation.updated_at = new Date().toISOString();
}

export function appendTimeline(id: string, entry: TimelineEntry): void {
  seed[id]?.timeline.push(entry);
}

export function appendMaterial(id: string, material: Material): void {
  seed[id]?.materials.push(material);
}

const monitors: Record<string, Monitor> = {
  "mon-1": {
    id: "mon-1",
    name: "英伟达先进封装供应链",
    subject: "英伟达 CoWoS 产能与供应商变化",
    strategy: "关注产能扩张、供应商变化、新合作方",
    frequency: "每天 09:00",
    status: "active",
    next_run_at: future(12 * 60),
    last_run_at: iso(24 * 60),
    created_at: iso(30 * 24 * 60),
    questions: ["产能扩张", "供应商变化", "CoWoS 产能", "新合作方"],
    websites: ["https://nvidianews.nvidia.com", "https://www.tsmc.com"],
  },
  "mon-2": {
    id: "mon-2",
    name: "碳化硅功率器件产能",
    subject: "国内碳化硅功率器件产能与良率",
    strategy: "关注新投产产线、良率数据、客户导入",
    frequency: "每周一 09:00",
    status: "paused",
    next_run_at: null,
    last_run_at: iso(3 * 24 * 60),
    created_at: iso(12 * 24 * 60),
    questions: ["新投产产线", "良率数据", "客户导入"],
    websites: ["https://www.infineon.com"],
  },
};

const monitorRuns: Record<string, MonitorRun[]> = {
  "mon-1": [
    {
      id: "mon-1-run-3",
      monitor_id: "mon-1",
      status: "succeeded",
      started_at: iso(24 * 60),
      finished_at: iso(24 * 60 - 20),
      changes: [
        {
          id: "mon-1-c1",
          kind: "new_source",
          importance: "high",
          summary: "新增材料：某头部封测厂扩产公告，涉及 CoWoS 产能",
          at: iso(24 * 60 - 5),
        },
        {
          id: "mon-1-c2",
          kind: "changed_fact",
          importance: "high",
          summary: "事实更新：2026 年 CoWoS 产能预估上调 12%",
          at: iso(24 * 60 - 10),
        },
        {
          id: "mon-1-c3",
          kind: "new_fact",
          importance: "normal",
          summary: "新增事实：新增一家国产设备商进入供应链",
          at: iso(24 * 60 - 15),
        },
      ],
      summary: "识别 1 个高重要性变化，新增 4 条材料",
    },
    {
      id: "mon-1-run-2",
      monitor_id: "mon-1",
      status: "succeeded",
      started_at: iso(2 * 24 * 60),
      finished_at: iso(2 * 24 * 60 - 18),
      changes: [
        {
          id: "mon-1-c4",
          kind: "new_fact",
          importance: "normal",
          summary: "新增事实：供应商报价周期缩短",
          at: iso(2 * 24 * 60 - 6),
        },
      ],
      summary: "无重大变化，新增 1 条材料",
    },
  ],
  "mon-2": [
    {
      id: "mon-2-run-1",
      monitor_id: "mon-2",
      status: "succeeded",
      started_at: iso(3 * 24 * 60),
      finished_at: iso(3 * 24 * 60 - 15),
      changes: [
        {
          id: "mon-2-c1",
          kind: "new_fact",
          importance: "normal",
          summary: "新增事实：某厂商 8 英寸线良率爬坡至 65%",
          at: iso(3 * 24 * 60 - 8),
        },
      ],
      summary: "新增 3 项事实",
    },
  ],
};

export function listMonitors(): Monitor[] {
  return Object.values(monitors).sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export function getMonitor(id: string): MonitorDetail | undefined {
  const monitor = monitors[id];
  if (!monitor) return undefined;
  return { monitor, runs: monitorRuns[id] ?? [] };
}

export function createMonitor(input: {
  name: string;
  subject: string;
  strategy: string;
  frequency: string;
  questions: string[];
  websites: string[];
}): Monitor {
  const id = `mon-${uid().slice(0, 8)}`;
  const monitor: Monitor = {
    id,
    ...input,
    status: "active",
    next_run_at: future(24 * 60),
    last_run_at: null,
    created_at: now(),
  };
  monitors[id] = monitor;
  monitorRuns[id] = [];
  return monitor;
}

export function toggleMonitor(id: string): Monitor | undefined {
  const monitor = monitors[id];
  if (!monitor) return undefined;
  monitor.status = monitor.status === "active" ? "paused" : "active";
  monitor.next_run_at = monitor.status === "active" ? future(24 * 60) : null;
  return monitor;
}

export function runMonitorNow(id: string): MonitorRun {
  const run: MonitorRun = {
    id: `mon-${id}-run-${uid().slice(0, 8)}`,
    monitor_id: id,
    status: "succeeded",
    started_at: now(),
    finished_at: now(),
    changes: [
      {
        id: uid(),
        kind: "new_fact",
        importance: "normal",
        summary: "立即运行完成，新增 2 项事实",
        at: now(),
      },
    ],
    summary: "立即运行完成",
  };
  if (!monitorRuns[id]) monitorRuns[id] = [];
  monitorRuns[id].unshift(run);
  return run;
}

const factChecks: Record<string, FactCheck> = {
  "fc-1": {
    id: "fc-1",
    claim: "长电科技是全球第三大半导体封测厂商",
    understanding: "断言指长电科技按营收在全球封测（OSAT）企业中排名第三。",
    questions: ["长电科技 2025 年封测营收是多少？", "全球封测企业营收排名口径是什么？"],
    status: "completed",
    verdict: "mostly_supported",
    evidence_sufficiency: "medium",
    independent_sources: 3,
    primary_sources: 1,
    counter_evidence: 1,
    evidence: [
      {
        id: "fc-1-e1",
        relation: "supports",
        quote: "按 2025 年营收计，长电科技位列全球封测企业第三位。",
        source_title: "全球封测行业排名 2025",
        source_url: "https://example.com/osat-ranking-2025",
      },
      {
        id: "fc-1-e2",
        relation: "supports",
        quote: "长电科技 2025 年营收约 360 亿元，同比增长 12%。",
        source_title: "长电科技 2025 年报",
        source_url: "https://example.com/jcet-annual",
      },
      {
        id: "fc-1-e3",
        relation: "contradicts",
        quote: "部分第三方统计将长电排位第四，因口径差异（含/不含日月光子公司）。",
        source_title: "封测市场份额口径辨析",
        source_url: "https://example.com/osat-share-caveat",
      },
    ],
    timeline: [
      { id: "fc-1-t1", kind: "intent", label: "理解待核验断言", at: iso(60) },
      { id: "fc-1-t2", kind: "search_plan", label: "规划核验检索", at: iso(59) },
      {
        id: "fc-1-t3",
        kind: "search",
        label: "检索权威来源",
        detail: "命中 9 个来源",
        at: iso(58),
      },
      {
        id: "fc-1-t4",
        kind: "evidence",
        label: "提取正反证据",
        detail: "2 支持 · 1 反驳",
        at: iso(57),
      },
      {
        id: "fc-1-t5",
        kind: "decision",
        label: "形成核验结论",
        detail: "基本支持 · 证据充分度中",
        at: iso(56),
      },
    ],
    created_at: iso(60),
  },
};

export function listFactChecks(): FactCheck[] {
  return Object.values(factChecks).sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export function getFactCheck(id: string): FactCheck | undefined {
  return factChecks[id];
}

export function createFactCheck(claim: string): FactCheck {
  const id = `fc-${uid().slice(0, 8)}`;
  const factCheck: FactCheck = {
    id,
    claim,
    understanding: "",
    questions: [],
    status: "running",
    verdict: null,
    evidence_sufficiency: null,
    independent_sources: 0,
    primary_sources: 0,
    counter_evidence: 0,
    evidence: [],
    timeline: [],
    created_at: now(),
  };
  factChecks[id] = factCheck;
  return factCheck;
}

export function updateFactCheck(id: string, patch: Partial<FactCheck>): FactCheck | undefined {
  const current = factChecks[id];
  if (!current) return undefined;
  factChecks[id] = { ...current, ...patch };
  return factChecks[id];
}

export function appendFactEvidence(id: string, evidence: FactEvidence): void {
  factChecks[id]?.evidence.push(evidence);
}

export function appendFactCheckTimeline(id: string, entry: TimelineEntry): void {
  factChecks[id]?.timeline.push(entry);
}

export function generateBrief(prompt: string): ResearchBrief {
  return {
    goal: prompt.trim(),
    scope: "公开信息为主，覆盖企业披露、行业报告与第三方研究",
    questions: ["背景与现状", "主要参与者", "关键变化与风险"],
    key_entities: [],
    suggested_sources: ["行业白皮书", "企业年报", "第三方研究"],
  };
}

export function startResearchConversation(topic: string, brief: ResearchBrief): Conversation {
  const id = `conv-${uid().slice(0, 8)}`;
  const conversation: Conversation = {
    id,
    title: topic.slice(0, 18),
    status: "intake",
    updated_at: now(),
    run_status: null,
    run_phase: null,
  };
  const questions: ResearchQuestion[] = brief.questions.map((text, index) => ({
    id: `${id}-q${index}`,
    text,
    status: "pending",
    evidence_count: 0,
    coverage_note: "",
  }));
  seed[id] = projection(conversation, [], [], [], brief, questions, []);
  return conversation;
}

export function systemStatus(): SystemStatus {
  return {
    model: { name: "qwen3.8-27B", configured: true },
    search: { name: "SearXNG", configured: true },
    processors: { tesseract: true, ffmpeg: true, whisper: false },
  };
}

const taskFacts: Record<string, LibraryFact[]> = {
  "conv-1": [
    {
      id: "conv-1-f1",
      statement: "国内先进封装市场高度集中于长电科技、通富微电、华天科技三家",
      status: "accepted",
      updated_at: iso(50),
    },
    {
      id: "conv-1-f2",
      statement: "高端 CoWoS 产能仍由台积电主导",
      status: "accepted",
      updated_at: iso(49),
    },
    {
      id: "conv-1-f3",
      statement: "细分封装工艺良率数据缺乏独立来源",
      status: "disputed",
      updated_at: iso(48),
    },
  ],
  "conv-2": [
    {
      id: "conv-2-f1",
      statement: "AI 训练芯片供应链关键瓶颈集中在 HBM 与先进制程产能",
      status: "accepted",
      updated_at: iso(40),
    },
    {
      id: "conv-2-f2",
      statement: "国产替代在封测环节进展最快",
      status: "accepted",
      updated_at: iso(39),
    },
  ],
  "conv-3": [
    {
      id: "conv-3-f1",
      statement: "某厂商 8 英寸线良率爬坡至 65%",
      status: "disputed",
      updated_at: iso(3 * 24 * 60),
    },
  ],
};

const taskEvidence: Record<string, FactEvidence[]> = {
  "conv-1": [
    {
      id: "conv-1-e1",
      relation: "supports",
      quote: "2025 年国内先进封装市场规模约 850 亿元，同比增长 21%。",
      source_title: "中国先进封装产业白皮书 2026",
      source_url: "https://example.com/advanced-packaging-2026",
    },
    {
      id: "conv-1-e2",
      relation: "supports",
      quote: "长电、通富、华天合计份额约 38%。",
      source_title: "长电科技 2025 年报",
      source_url: "https://example.com/jcet-annual",
    },
  ],
  "conv-2": [
    {
      id: "conv-2-e1",
      relation: "supports",
      quote: "HBM 供应高度集中于少数厂商，扩产周期长。",
      source_title: "AI 芯片供应链分析",
      source_url: "https://example.com/ai-supply-chain",
    },
  ],
  "conv-3": [],
};

const taskReports: Record<string, Report | null> = {
  "conv-1": {
    id: "report-1",
    version: 2,
    status: "published",
    created_at: iso(48),
    content: `# 先进封装产业竞争格局调研报告

## 结论摘要

国内先进封装市场高度集中于长电科技、通富微电、华天科技三家，合计份额约 38%；高端 CoWoS 产能仍由台积电主导。

## 市场规模与格局

2025 年国内先进封装市场规模约 850 亿元，同比增长 21%。

## 主要玩家

- 长电科技：营收规模居首，客户结构多元。
- 通富微电：聚焦高端封装，进入头部芯片客户供应链。
- 华天科技：份额稳定，产品线覆盖中低端。

## 缺口与风险

细分封装工艺良率数据缺乏独立来源，仅依赖厂商二手材料。
`,
  },
  "conv-2": {
    id: "report-2",
    version: 1,
    status: "published",
    created_at: iso(38),
    content: `# AI 芯片供应链风险调研报告

## 结论摘要

AI 训练芯片供应链的关键瓶颈集中在 HBM 与先进制程产能。

## 关键发现

- HBM 供应高度集中于少数厂商，扩产周期长。
- 国产替代在封测环节进展最快，长电、通富已进入头部客户供应链。
`,
  },
  "conv-3": null,
};

export function listLibrary(): Library {
  const research: LibraryResearchRecord[] = Object.values(seed).map((item) => {
    const materials = item.materials;
    const facts = taskFacts[item.conversation.id] ?? [];
    const evidence = taskEvidence[item.conversation.id] ?? [];
    const seen = new Set<string>();
    const sources: LibrarySource[] = [];
    for (const doc of materials) {
      if (seen.has(doc.url)) continue;
      seen.add(doc.url);
      sources.push({ id: doc.id, name: doc.title, type: doc.source_type, url: doc.url });
    }
    for (const entry of evidence) {
      if (seen.has(entry.source_url)) continue;
      seen.add(entry.source_url);
      sources.push({
        id: entry.id,
        name: entry.source_title,
        type: "证据来源",
        url: entry.source_url,
      });
    }
    return {
      id: item.conversation.id,
      title: item.conversation.title,
      updated_at: item.conversation.updated_at,
      materials,
      facts,
      evidence,
      sources,
      report: taskReports[item.conversation.id] ?? null,
      brief: item.brief,
      questions: item.questions,
      timeline: item.timeline,
    };
  });
  research.sort((a, b) => b.updated_at.localeCompare(a.updated_at));

  const monitorRecords = Object.keys(monitors).flatMap((id) => {
    const detail = getMonitor(id);
    return detail ? [detail] : [];
  });

  return {
    research,
    monitors: monitorRecords,
    factChecks: listFactChecks(),
  };
}

const searchSources: Record<string, SearchSource> = {
  "src-1": {
    id: "src-1",
    name: "SearXNG",
    url: "http://127.0.0.1:8888",
    enabled: true,
    cookies: "",
  },
  "src-2": {
    id: "src-2",
    name: "微信公众号",
    url: "https://mp.weixin.qq.com",
    enabled: false,
    cookies: "",
  },
  "src-3": {
    id: "src-3",
    name: "必应",
    url: "https://www.bing.com",
    enabled: true,
    cookies: "",
  },
};

export function listSearchSources(): SearchSource[] {
  return Object.values(searchSources).sort((a, b) => a.name.localeCompare(b.name));
}

export function toggleSearchSource(id: string): SearchSource | undefined {
  const source = searchSources[id];
  if (!source) return undefined;
  source.enabled = !source.enabled;
  return source;
}

export function updateSearchSource(
  id: string,
  patch: Partial<Pick<SearchSource, "cookies" | "enabled">>,
): SearchSource | undefined {
  const source = searchSources[id];
  if (!source) return undefined;
  searchSources[id] = { ...source, ...patch };
  return searchSources[id];
}

export function addSearchSource(input: { name: string; url: string }): SearchSource {
  const id = `src-${uid().slice(0, 8)}`;
  const source: SearchSource = {
    id,
    name: input.name,
    url: input.url,
    enabled: true,
    cookies: "",
  };
  searchSources[id] = source;
  return source;
}

const aiSearchTools: Record<string, AiSearchTool> = {
  "tool-exa": {
    id: "tool-exa",
    name: "Exa",
    description: "语义/神经搜索，擅长寻找相似页面与深层内容",
    enabled: false,
    api_key: "",
    api_key_env: "EXA_API_KEY",
  },
  "tool-brave": {
    id: "tool-brave",
    name: "Brave Search",
    description: "独立网页索引，覆盖新闻与实时网页",
    enabled: true,
    api_key: "",
    api_key_env: "BRAVE_API_KEY",
  },
  "tool-tavily": {
    id: "tool-tavily",
    name: "Tavily",
    description: "面向 AI Agent 的搜索 API，结构化返回",
    enabled: false,
    api_key: "",
    api_key_env: "TAVILY_API_KEY",
  },
};

export function listAiSearchTools(): AiSearchTool[] {
  return Object.values(aiSearchTools).sort((a, b) => a.name.localeCompare(b.name));
}

export function toggleAiSearchTool(id: string): AiSearchTool | undefined {
  const tool = aiSearchTools[id];
  if (!tool) return undefined;
  tool.enabled = !tool.enabled;
  return tool;
}

export function updateAiSearchToolApiKey(id: string, apiKey: string): AiSearchTool | undefined {
  const tool = aiSearchTools[id];
  if (!tool) return undefined;
  tool.api_key = apiKey;
  return tool;
}

const mediaJobs: Record<string, MediaJob> = {
  "media-1": {
    id: "media-1",
    filename: "供应商访谈-20260901.mp4",
    kind: "video",
    size: 128_974_848,
    status: "completed",
    created_at: iso(120),
    summary: "受访者确认 2026 年 CoWoS 产能上调，并透露一家国产设备商已进入供应链。",
    segments: [
      {
        id: "media-1-s1",
        start: 0,
        end: 12,
        text: "各位好，今天谈一下我们先进封装产能的进展。",
        speaker: "采访者",
      },
      {
        id: "media-1-s2",
        start: 12,
        end: 34,
        text: "我们今年的 CoWoS 产能较去年上调了大约百分之十二。",
        speaker: "受访者",
      },
      {
        id: "media-1-s3",
        start: 34,
        end: 55,
        text: "另外有一家国产设备厂商，已经进入了我们的供应链，目前在做验证。",
        speaker: "受访者",
      },
      {
        id: "media-1-s4",
        start: 55,
        end: 71,
        text: "关于良率，目前还在爬坡阶段，具体数字不方便透露。",
        speaker: "受访者",
      },
    ],
    facts: [
      {
        id: "media-1-f1",
        statement: "2026 年 CoWoS 产能较去年上调约 12%",
        segment_id: "media-1-s2",
        status: "accepted",
      },
      {
        id: "media-1-f2",
        statement: "一家国产设备商已进入该厂供应链",
        segment_id: "media-1-s3",
        status: "accepted",
      },
    ],
    evidence: [
      {
        id: "media-1-e1",
        relation: "supports",
        quote: "我们今年的 CoWoS 产能较去年上调了大约百分之十二。",
        start: 12,
        end: 34,
      },
      {
        id: "media-1-e2",
        relation: "supports",
        quote: "另外有一家国产设备厂商，已经进入了我们的供应链。",
        start: 34,
        end: 55,
      },
    ],
  },
};

export function listMediaJobs(): MediaJob[] {
  return Object.values(mediaJobs).sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export function getMediaJob(id: string): MediaJob | undefined {
  return mediaJobs[id];
}

export function createMediaJob(input: {
  filename: string;
  kind: "audio" | "video";
  size: number;
}): MediaJob {
  const id = `media-${uid().slice(0, 8)}`;
  const job: MediaJob = {
    id,
    filename: input.filename,
    kind: input.kind,
    size: input.size,
    status: "transcribing",
    segments: [],
    facts: [],
    evidence: [],
    summary: null,
    created_at: now(),
  };
  mediaJobs[id] = job;
  return job;
}

export function updateMediaJob(id: string, patch: Partial<MediaJob>): MediaJob | undefined {
  const current = mediaJobs[id];
  if (!current) return undefined;
  mediaJobs[id] = { ...current, ...patch };
  return mediaJobs[id];
}

export function appendMediaSegment(id: string, segment: MediaSegment): void {
  mediaJobs[id]?.segments.push(segment);
}

export function appendMediaFact(id: string, fact: MediaFact): void {
  mediaJobs[id]?.facts.push(fact);
}

export function appendMediaEvidence(id: string, evidence: MediaEvidence): void {
  mediaJobs[id]?.evidence.push(evidence);
}
