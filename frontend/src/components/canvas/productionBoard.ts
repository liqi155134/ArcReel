import type { EpisodeMeta, LocalWorkflowGate, ScriptReviewState } from "@/types";

export type ProductionStageStatus =
  | "not_started"
  | "pending"
  | "blocked"
  | "needs_changes"
  | "approved"
  | "missing_artifact"
  | "locked";

export type ProductionIssueCode =
  | "qa_blocked"
  | "storyboard_rework"
  | "video_rework"
  | "export_rework"
  | "missing_prompt"
  | "missing_storyboard_artifact"
  | "missing_video_artifact"
  | "missing_export_artifact"
  | "review_unavailable";

export interface EpisodeProductionRow {
  episode: number;
  title: string;
  script: ProductionStageStatus;
  storyboard: ProductionStageStatus;
  video: ProductionStageStatus;
  export: ProductionStageStatus;
  issues: ProductionIssueCode[];
}

export interface EpisodeProductionSummary {
  total: number;
  qaBlocked: number;
  rework: number;
  missingPrompt: number;
  missingVideo: number;
  missingExport: number;
}

export const PRODUCTION_STAGE_LABELS: Record<ProductionStageStatus, string> = {
  not_started: "未开始",
  pending: "待审核",
  blocked: "QA阻塞",
  needs_changes: "需要修改",
  approved: "已通过",
  missing_artifact: "缺产物",
  locked: "锁定",
};

export const PRODUCTION_ISSUE_LABELS: Record<ProductionIssueCode, string> = {
  qa_blocked: "QA阻塞",
  storyboard_rework: "分镜返工",
  video_rework: "视频返工",
  export_rework: "导出返工",
  missing_prompt: "缺 Prompt",
  missing_storyboard_artifact: "缺分镜图",
  missing_video_artifact: "缺视频",
  missing_export_artifact: "缺成片",
  review_unavailable: "未读取",
};

function hasArtifact(state: ScriptReviewState, gate: LocalWorkflowGate): boolean {
  const artifact = state.local_workflow_artifacts[gate];
  return Boolean(artifact.path.trim() || artifact.url.trim());
}

function isGateAccepted(state: ScriptReviewState, gate: LocalWorkflowGate): boolean {
  const reviews = state.local_workflow_reviews;
  if (gate === "storyboard") {
    return (
      reviews.storyboard_reviewed === true ||
      reviews.storyboard_decision === "approved" ||
      reviews.storyboard_decision === "skipped"
    );
  }
  if (gate === "video") {
    return reviews.video_reviewed === true || reviews.video_decision === "approved" || reviews.video_decision === "skipped";
  }
  return reviews.export_reviewed === true || reviews.export_decision === "approved" || reviews.export_decision === "skipped";
}

function gateDecision(state: ScriptReviewState, gate: LocalWorkflowGate): string {
  if (gate === "storyboard") return state.local_workflow_reviews.storyboard_decision;
  if (gate === "video") return state.local_workflow_reviews.video_decision;
  return state.local_workflow_reviews.export_decision;
}

function deriveScriptStatus(state: ScriptReviewState | null | undefined): ProductionStageStatus {
  if (!state || state.status === "no_step1" || state.status === "not_applicable") return "not_started";
  if (state.qa_gate_status === "blocked") return "blocked";
  if (state.status === "confirmed") return "approved";
  return "pending";
}

function deriveGateStatus(
  state: ScriptReviewState | null | undefined,
  gate: LocalWorkflowGate,
  upstreamReady: boolean,
): ProductionStageStatus {
  if (!state) return "not_started";
  if (!upstreamReady) return "locked";
  if (gateDecision(state, gate) === "needs_changes") return "needs_changes";
  if (isGateAccepted(state, gate)) return hasArtifact(state, gate) ? "approved" : "missing_artifact";
  return "pending";
}

function rowIssues(state: ScriptReviewState | null | undefined, row: Omit<EpisodeProductionRow, "issues">): ProductionIssueCode[] {
  const issues: ProductionIssueCode[] = [];
  if (!state) return ["review_unavailable"];
  if (row.script === "blocked") issues.push("qa_blocked");
  if (row.storyboard === "needs_changes") issues.push("storyboard_rework");
  if (row.video === "needs_changes") issues.push("video_rework");
  if (row.export === "needs_changes") issues.push("export_rework");
  if (!state.local_workflow_artifacts.seedance_prompt.trim()) issues.push("missing_prompt");
  if (row.storyboard === "missing_artifact") issues.push("missing_storyboard_artifact");
  if (row.video === "missing_artifact") issues.push("missing_video_artifact");
  if (row.export === "missing_artifact") issues.push("missing_export_artifact");
  return issues;
}

export function deriveEpisodeProductionRows(
  episodes: readonly EpisodeMeta[],
  reviewStates: Partial<Record<number, ScriptReviewState | null | undefined>>,
): EpisodeProductionRow[] {
  return episodes.map((episode) => {
    const state = reviewStates[episode.episode];
    const script = deriveScriptStatus(state);
    const storyboard = deriveGateStatus(state, "storyboard", script === "approved");
    const storyboardAccepted = Boolean(state && isGateAccepted(state, "storyboard") && gateDecision(state, "storyboard") !== "needs_changes");
    const video = deriveGateStatus(state, "video", script === "approved" && storyboardAccepted);
    const videoAccepted = Boolean(state && isGateAccepted(state, "video") && gateDecision(state, "video") !== "needs_changes");
    const exportStage = deriveGateStatus(state, "export", script === "approved" && storyboardAccepted && videoAccepted);
    const base = {
      episode: episode.episode,
      title: episode.title || `E${episode.episode}`,
      script,
      storyboard,
      video,
      export: exportStage,
    };
    return { ...base, issues: rowIssues(state, base) };
  });
}

export function summarizeEpisodeProductionRows(rows: readonly EpisodeProductionRow[]): EpisodeProductionSummary {
  return {
    total: rows.length,
    qaBlocked: rows.filter((row) => row.issues.includes("qa_blocked")).length,
    rework: rows.filter((row) =>
      row.issues.includes("storyboard_rework") ||
      row.issues.includes("video_rework") ||
      row.issues.includes("export_rework"),
    ).length,
    missingPrompt: rows.filter((row) => row.issues.includes("missing_prompt")).length,
    missingVideo: rows.filter((row) => row.issues.includes("missing_video_artifact")).length,
    missingExport: rows.filter((row) => row.issues.includes("missing_export_artifact")).length,
  };
}

function csvCell(value: string | number): string {
  const raw = String(value);
  if (!/[",\n]/.test(raw)) return raw;
  return `"${raw.replace(/"/g, '""')}"`;
}

export function buildEpisodeProductionCsv(rows: readonly EpisodeProductionRow[]): string {
  const header = ["episode", "title", "script", "storyboard", "video", "export", "issues"];
  const body = rows.map((row) =>
    [
      row.episode,
      row.title,
      PRODUCTION_STAGE_LABELS[row.script],
      PRODUCTION_STAGE_LABELS[row.storyboard],
      PRODUCTION_STAGE_LABELS[row.video],
      PRODUCTION_STAGE_LABELS[row.export],
      row.issues.map((issue) => PRODUCTION_ISSUE_LABELS[issue]).join(";"),
    ]
      .map(csvCell)
      .join(","),
  );
  return [header.join(","), ...body].join("\n");
}
