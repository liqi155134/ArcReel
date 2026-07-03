import type { LocalWorkflowDecision, ScriptReviewQaGateStatus, ScriptReviewStatus } from "@/types";

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
  qaGateStatus: ScriptReviewQaGateStatus;
  storyboardDecision?: LocalWorkflowDecision;
  videoDecision?: LocalWorkflowDecision;
  exportDecision?: LocalWorkflowDecision;
}

function scriptStatus(input: LocalWorkflowInput): LocalWorkflowStageStatus {
  if (input.qaGateStatus === "blocked") return "blocked";
  if (input.reviewStatus === "confirmed") return input.qaGateStatus === "warning" ? "warning" : "complete";
  if (input.reviewStatus === "no_step1") return "ready";
  if (input.qaGateStatus === "warning") return "warning";
  return "ready";
}

function gateStatus(
  decision: LocalWorkflowDecision | undefined,
  upstreamComplete: boolean,
): LocalWorkflowStageStatus {
  if (!upstreamComplete) return "locked";
  if (decision === "needs_changes") return "warning";
  if (decision === "approved" || decision === "skipped") return "complete";
  return "ready";
}

export function deriveLocalWorkflowStages(input: LocalWorkflowInput): LocalWorkflowStage[] {
  const script = scriptStatus(input);
  const scriptBlocksDownstream = script === "blocked";
  const scriptConfirmed = input.reviewStatus === "confirmed" && !scriptBlocksDownstream;
  const scriptAllowsManualStoryboard = !scriptBlocksDownstream && input.reviewStatus !== "no_step1";

  const storyboard = gateStatus(input.storyboardDecision, scriptConfirmed);
  const storyboardStatus = storyboard === "locked" && scriptAllowsManualStoryboard ? "ready" : storyboard;
  const video = gateStatus(input.videoDecision, storyboardStatus === "complete");
  const exportStatus = gateStatus(input.exportDecision, video === "complete");

  return [
    { id: "brief_gate", status: "complete" },
    { id: "script_gate", status: script },
    { id: "asset_gate", status: scriptBlocksDownstream ? "locked" : "ready" },
    { id: "storyboard_gate", status: scriptBlocksDownstream ? "locked" : storyboardStatus },
    { id: "video_gate", status: video },
    { id: "export_gate", status: exportStatus },
  ];
}
