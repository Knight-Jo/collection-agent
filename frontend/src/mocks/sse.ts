import type {
  FactEvidence,
  Material,
  MediaEvidence,
  MediaFact,
  MediaSegment,
  RunPhase,
  RunStatus,
  TimelineEntry,
  Verdict,
} from "@/api/types";
import { uid } from "@/lib/utils";
import {
  appendFactCheckTimeline,
  appendFactEvidence,
  appendMaterial,
  appendMediaEvidence,
  appendMediaFact,
  appendMediaSegment,
  appendMessage,
  appendTimeline,
  updateConversation,
  updateFactCheck,
  updateMediaJob,
} from "./db";

export type AgentEvent =
  | { type: "answer.started" }
  | { type: "answer.delta"; delta: string }
  | { type: "answer.completed" }
  | { type: "run.status"; status: RunStatus }
  | { type: "run.phase"; phase: RunPhase }
  | { type: "timeline"; entry: TimelineEntry }
  | { type: "material"; material: Material }
  | { type: "refetch" };

type Handler = (event: AgentEvent) => void;

const listeners = new Map<string, Set<Handler>>();

export function subscribe(conversationId: string, handler: Handler): () => void {
  const set = listeners.get(conversationId) ?? new Set<Handler>();
  set.add(handler);
  listeners.set(conversationId, set);
  return () => {
    set.delete(handler);
    if (set.size === 0) listeners.delete(conversationId);
  };
}

function emit(conversationId: string, event: AgentEvent): void {
  listeners.get(conversationId)?.forEach((handler) => {
    handler(event);
  });
}

const REPLIES = [
  "根据公开材料，我已梳理出该主题的初步结论：\n\n1. 市场格局较为集中，头部三家合计占据约 38% 的份额；\n2. 高端产能仍存在明显依赖，国产替代集中在封测环节；\n3. 近期政策与产能扩张信号明确，可关注后续良率数据。\n\n如需继续，我可以进一步挖掘细分工艺或补充更多一手来源。",
];

const MATERIALS: Material[] = [
  {
    id: "doc-new-1",
    title: "2026 年行业景气度调研",
    url: "https://example.com/industry-2026",
    source_type: "行业报告",
    rating: 4,
    description: "最新一期行业调研，数据口径较新。",
  },
  {
    id: "doc-new-2",
    title: "头部厂商产能公告",
    url: "https://example.com/capacity-note",
    source_type: "企业披露",
    rating: 4,
    description: "官方扩产公告，含投产时间表。",
  },
];

const TRAIL: Array<Omit<TimelineEntry, "id" | "at">> = [
  { kind: "intent", label: "理解调研目标", detail: "拆解关键问题并确认范围" },
  { kind: "search_plan", label: "生成检索计划", detail: "规划 8 组检索方向" },
  { kind: "search", label: "执行检索", detail: "命中 19 个来源，去重保留 8 个" },
  { kind: "material", label: "材料入库", detail: "抓取并提取 6 份文档" },
  { kind: "evidence", label: "证据核验", detail: "提取 11 条证据" },
  { kind: "coverage", label: "覆盖率评估", detail: "覆盖率 86%" },
  { kind: "decision", label: "提交研究结果", detail: "已提交检查点" },
];

function step(delayMs: number, fn: () => void): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(() => {
      fn();
      resolve();
    }, delayMs);
  });
}

export async function simulateReply(conversationId: string, question: string): Promise<void> {
  updateConversation(conversationId, { title: question.slice(0, 18), status: "active" });
  emit(conversationId, { type: "run.status", status: "queued" });

  await step(300, () => {
    emit(conversationId, { type: "run.status", status: "running" });
    emit(conversationId, { type: "run.phase", phase: "planning" });
    emit(conversationId, {
      type: "timeline",
      entry: { ...TRAIL[0], id: uid(), at: new Date().toISOString() },
    });
    updateConversation(conversationId, { run_status: "running", run_phase: "planning" });
  });

  await step(700, () => {
    const entry: TimelineEntry = {
      ...TRAIL[1],
      id: uid(),
      at: new Date().toISOString(),
    };
    appendTimeline(conversationId, entry);
    emit(conversationId, { type: "timeline", entry });
    emit(conversationId, { type: "answer.started" });
  });

  for (const chunk of REPLIES[0]) {
    await step(28, () => emit(conversationId, { type: "answer.delta", delta: chunk }));
  }

  await step(300, () => {
    emit(conversationId, { type: "run.phase", phase: "collecting" });
    updateConversation(conversationId, { run_phase: "collecting" });
    const entry: TimelineEntry = {
      ...TRAIL[2],
      id: uid(),
      at: new Date().toISOString(),
    };
    appendTimeline(conversationId, entry);
    emit(conversationId, { type: "timeline", entry });
  });

  for (const material of MATERIALS) {
    await step(400, () => {
      appendMaterial(conversationId, material);
      emit(conversationId, { type: "material", material });
    });
  }

  for (const item of TRAIL.slice(3)) {
    await step(400, () => {
      const entry: TimelineEntry = {
        ...item,
        id: uid(),
        at: new Date().toISOString(),
      };
      appendTimeline(conversationId, entry);
      emit(conversationId, { type: "timeline", entry });
    });
  }

  await step(300, () => {
    emit(conversationId, { type: "run.status", status: "succeeded" });
    emit(conversationId, { type: "run.phase", phase: "checkpointing" });
    updateConversation(conversationId, { run_status: "succeeded", run_phase: "checkpointing" });
    appendMessage(conversationId, {
      id: uid(),
      role: "assistant",
      content: REPLIES[0],
      status: "completed",
      citations: [
        {
          id: uid(),
          sequence: 1,
          title: MATERIALS[0].title,
          source_url: MATERIALS[0].url,
          quote_text: "头部三家合计占据约 38% 的份额。",
        },
      ],
    });
    emit(conversationId, { type: "answer.completed" });
    emit(conversationId, { type: "refetch" });
  });
}

export type FactCheckEvent =
  | { type: "timeline"; entry: TimelineEntry }
  | { type: "evidence"; evidence: FactEvidence }
  | { type: "verdict"; verdict: Verdict }
  | { type: "refetch" };

type FactCheckHandler = (event: FactCheckEvent) => void;

const factCheckListeners = new Map<string, Set<FactCheckHandler>>();

export function subscribeFactCheck(checkId: string, handler: FactCheckHandler): () => void {
  const set = factCheckListeners.get(checkId) ?? new Set<FactCheckHandler>();
  set.add(handler);
  factCheckListeners.set(checkId, set);
  return () => {
    set.delete(handler);
    if (set.size === 0) factCheckListeners.delete(checkId);
  };
}

function emitFactCheck(checkId: string, event: FactCheckEvent): void {
  factCheckListeners.get(checkId)?.forEach((handler) => {
    handler(event);
  });
}

const FACT_EVIDENCE: FactEvidence[] = [
  {
    id: uid(),
    relation: "supports",
    quote: "权威统计显示该表述与公开数据一致，核心数字得到两个独立来源交叉印证。",
    source_title: "行业权威统计",
    source_url: "https://example.com/authoritative",
  },
  {
    id: uid(),
    relation: "contradicts",
    quote: "另一来源的口径存在差异，主要分歧在统计边界（是否含关联子公司）。",
    source_title: "第三方口径辨析",
    source_url: "https://example.com/caveat",
  },
];

const FACT_TRAIL: Array<Omit<TimelineEntry, "id" | "at">> = [
  { kind: "intent", label: "理解待核验断言" },
  { kind: "search_plan", label: "规划核验检索", detail: "拆解为关键实体与时间范围" },
  { kind: "search", label: "检索权威来源", detail: "命中 7 个来源，去重保留 5 个" },
  { kind: "evidence", label: "提取正反证据" },
  { kind: "decision", label: "形成核验结论" },
];

function factStep(delayMs: number, fn: () => void): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(() => {
      fn();
      resolve();
    }, delayMs);
  });
}

export async function simulateFactCheck(checkId: string): Promise<void> {
  for (const item of FACT_TRAIL) {
    await factStep(420, () => {
      const entry: TimelineEntry = {
        ...item,
        id: uid(),
        at: new Date().toISOString(),
      };
      appendFactCheckTimeline(checkId, entry);
      emitFactCheck(checkId, { type: "timeline", entry });
    });
  }

  for (const evidence of FACT_EVIDENCE) {
    await factStep(380, () => {
      appendFactEvidence(checkId, evidence);
      emitFactCheck(checkId, { type: "evidence", evidence });
    });
  }

  await factStep(300, () => {
    const verdict: Verdict = "mostly_supported";
    updateFactCheck(checkId, {
      status: "completed",
      verdict,
      evidence_sufficiency: "medium",
      independent_sources: 3,
      primary_sources: 1,
      counter_evidence: 1,
      understanding: "已解析断言中的核心实体与排名口径。",
      questions: ["排名口径是否一致？", "是否存在独立来源交叉印证？"],
    });
    emitFactCheck(checkId, { type: "verdict", verdict });
    emitFactCheck(checkId, { type: "refetch" });
  });
}

export type MediaEvent =
  | { type: "segment"; segment: MediaSegment }
  | { type: "fact"; fact: MediaFact }
  | { type: "evidence"; evidence: MediaEvidence }
  | { type: "status"; status: "transcribing" | "analyzing" | "completed" }
  | { type: "refetch" };

type MediaHandler = (event: MediaEvent) => void;

const mediaListeners = new Map<string, Set<MediaHandler>>();

export function subscribeMedia(jobId: string, handler: MediaHandler): () => void {
  const set = mediaListeners.get(jobId) ?? new Set<MediaHandler>();
  set.add(handler);
  mediaListeners.set(jobId, set);
  return () => {
    set.delete(handler);
    if (set.size === 0) mediaListeners.delete(jobId);
  };
}

function emitMedia(jobId: string, event: MediaEvent): void {
  mediaListeners.get(jobId)?.forEach((handler) => {
    handler(event);
  });
}

function mediaStep(delayMs: number, fn: () => void): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(() => {
      fn();
      resolve();
    }, delayMs);
  });
}

const MOCK_SEGMENTS: Array<Omit<MediaSegment, "id">> = [
  { start: 0, end: 11, text: "大家好，今天我们谈一下近期产能扩张的进展。", speaker: "采访者" },
  {
    start: 11,
    end: 30,
    text: "我们新增了一条产线，预计下季度投产，良率目前在爬坡。",
    speaker: "受访者",
  },
  {
    start: 30,
    end: 47,
    text: "关于客户导入，有两家新客户已经完成验证并开始小批量供货。",
    speaker: "受访者",
  },
  { start: 47, end: 60, text: "具体的良率数字我们不便对外披露。", speaker: "受访者" },
];

const MOCK_MEDIA_FACTS: Array<Omit<MediaFact, "id">> = [
  { statement: "新增一条产线，预计下季度投产", segment_id: "", status: "accepted" },
  { statement: "两家新客户完成验证并开始小批量供货", segment_id: "", status: "accepted" },
];

const MOCK_MEDIA_EVIDENCE: Array<Omit<MediaEvidence, "id">> = [
  { relation: "supports", quote: "我们新增了一条产线，预计下季度投产。", start: 11, end: 30 },
  { relation: "supports", quote: "有两家新客户已经完成验证并开始小批量供货。", start: 30, end: 47 },
];

export async function simulateMediaAnalysis(jobId: string): Promise<void> {
  for (const segment of MOCK_SEGMENTS) {
    await mediaStep(500, () => {
      const full: MediaSegment = { ...segment, id: uid() };
      appendMediaSegment(jobId, full);
      emitMedia(jobId, { type: "segment", segment: full });
    });
  }

  await mediaStep(300, () => {
    updateMediaJob(jobId, { status: "analyzing" });
    emitMedia(jobId, { type: "status", status: "analyzing" });
  });

  for (const fact of MOCK_MEDIA_FACTS) {
    await mediaStep(400, () => {
      const full: MediaFact = { ...fact, id: uid() };
      appendMediaFact(jobId, full);
      emitMedia(jobId, { type: "fact", fact: full });
    });
  }

  for (const evidence of MOCK_MEDIA_EVIDENCE) {
    await mediaStep(400, () => {
      const full: MediaEvidence = { ...evidence, id: uid() };
      appendMediaEvidence(jobId, full);
      emitMedia(jobId, { type: "evidence", evidence: full });
    });
  }

  await mediaStep(300, () => {
    updateMediaJob(jobId, {
      status: "completed",
      summary: "识别到产线扩张与客户导入两条关键情报，相关事实已抽取。",
    });
    emitMedia(jobId, { type: "status", status: "completed" });
    emitMedia(jobId, { type: "refetch" });
  });
}
