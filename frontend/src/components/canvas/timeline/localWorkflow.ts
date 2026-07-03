import type { QaGateStatus, ScriptReviewStatus } from "@/types";

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
  videoReviewed?: boolean;
  exportReviewed?: boolean;
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
  const storyboard: LocalWorkflowStageStatus = scriptBlocksDownstream
    ? "locked"
    : scriptConfirmed && input.storyboardReviewed
      ? "complete"
      : scriptAllowsManualStoryboard
        ? "ready"
        : "locked";
  const video: LocalWorkflowStageStatus = input.videoReviewed
    ? "complete"
    : storyboard === "complete"
      ? "ready"
      : "locked";
  const exportStatus: LocalWorkflowStageStatus = input.exportReviewed ? "complete" : input.videoReviewed ? "ready" : "locked";

  return [
    { id: "brief_gate", status: "complete" },
    { id: "script_gate", status: script },
    { id: "asset_gate", status: scriptBlocksDownstream ? "locked" : "ready" },
    { id: "storyboard_gate", status: storyboard },
    { id: "video_gate", status: video },
    { id: "export_gate", status: exportStatus },
  ];
}
