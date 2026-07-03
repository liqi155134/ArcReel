import type { LocalWorkflowDecision, QaGateStatus, ScriptReviewStatus } from "@/types";

export type LocalWorkflowStageId =
  | "brief_gate"
  | "script_gate"
  | "asset_gate"
  | "storyboard_gate"
  | "video_gate"
  | "export_gate";

export type LocalWorkflowStageStatus = "complete" | "ready" | "warning" | "blocked" | "locked";

export interface LocalWorkflowStage {
  id: LocalWorkflowStageId;
  status: LocalWorkflowStageStatus;
}

export interface LocalWorkflowInput {
  reviewStatus: ScriptReviewStatus;
  qaGateStatus: QaGateStatus;
  storyboardReviewed?: boolean;
  storyboardDecision?: LocalWorkflowDecision;
  videoReviewed?: boolean;
  videoDecision?: LocalWorkflowDecision;
  exportReviewed?: boolean;
  exportDecision?: LocalWorkflowDecision;
}

function scriptStatus(input: LocalWorkflowInput): LocalWorkflowStageStatus {
  if (input.qaGateStatus === "blocked") return "blocked";
  if (input.reviewStatus === "confirmed") return input.qaGateStatus === "warning" ? "warning" : "complete";
  if (input.reviewStatus === "no_step1") return "ready";
  if (input.qaGateStatus === "warning") return "warning";
  return "ready";
}

export function deriveLocalWorkflowStages(input: LocalWorkflowInput): LocalWorkflowStage[] {
  const script = scriptStatus(input);
  const scriptBlocksDownstream = script === "blocked";
  const scriptConfirmed = input.reviewStatus === "confirmed";
  const scriptAllowsManualStoryboard = !scriptBlocksDownstream && input.reviewStatus !== "no_step1";
  const storyboardNeedsRework = input.storyboardDecision === "needs_changes";
  const videoNeedsRework = input.videoDecision === "needs_changes";
  const exportNeedsRework = input.exportDecision === "needs_changes";
  const storyboard: LocalWorkflowStageStatus = scriptBlocksDownstream
    ? "locked"
    : storyboardNeedsRework
      ? "warning"
    : scriptConfirmed && input.storyboardReviewed
      ? "complete"
      : scriptAllowsManualStoryboard
        ? "ready"
        : "locked";
  const video: LocalWorkflowStageStatus = storyboard !== "complete"
    ? "locked"
    : videoNeedsRework
      ? "warning"
      : input.videoReviewed
        ? "complete"
        : "ready";
  const exportStatus: LocalWorkflowStageStatus = video !== "complete"
    ? "locked"
    : exportNeedsRework
      ? "warning"
      : input.exportReviewed
        ? "complete"
        : "ready";

  return [
    { id: "brief_gate", status: "complete" },
    { id: "script_gate", status: script },
    { id: "asset_gate", status: scriptBlocksDownstream ? "locked" : "ready" },
    { id: "storyboard_gate", status: storyboard },
    { id: "video_gate", status: video },
    { id: "export_gate", status: exportStatus },
  ];
}
