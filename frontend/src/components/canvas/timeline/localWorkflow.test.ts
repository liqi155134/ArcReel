import { describe, expect, it } from "vitest";
import { deriveLocalWorkflowStages } from "./localWorkflow";

function stageMap(input: Parameters<typeof deriveLocalWorkflowStages>[0]) {
  return Object.fromEntries(deriveLocalWorkflowStages(input).map((stage) => [stage.id, stage.status]));
}

describe("deriveLocalWorkflowStages", () => {
  it("blocks downstream storyboard video and export when deterministic script QA is blocked", () => {
    const stages = stageMap({ reviewStatus: "pending_review", qaGateStatus: "blocked" });

    expect(stages.script_gate).toBe("blocked");
    expect(stages.storyboard_gate).toBe("locked");
    expect(stages.video_gate).toBe("locked");
    expect(stages.export_gate).toBe("locked");
  });

  it("allows manual storyboard preparation but locks video while script review is only warning/pending", () => {
    const stages = stageMap({ reviewStatus: "pending_review", qaGateStatus: "warning" });

    expect(stages.script_gate).toBe("warning");
    expect(stages.asset_gate).toBe("ready");
    expect(stages.storyboard_gate).toBe("ready");
    expect(stages.video_gate).toBe("locked");
  });

  it("unlocks video only after script is confirmed and storyboard gate is approved", () => {
    const stages = stageMap({
      reviewStatus: "confirmed",
      qaGateStatus: "clear",
      storyboardDecision: "approved",
    });

    expect(stages.script_gate).toBe("complete");
    expect(stages.storyboard_gate).toBe("complete");
    expect(stages.video_gate).toBe("ready");
    expect(stages.export_gate).toBe("locked");
  });

  it("marks needs_changes as warning and locks downstream stages", () => {
    const stages = stageMap({
      reviewStatus: "confirmed",
      qaGateStatus: "clear",
      storyboardDecision: "needs_changes",
      videoDecision: "approved",
      exportDecision: "approved",
    });

    expect(stages.storyboard_gate).toBe("warning");
    expect(stages.video_gate).toBe("locked");
    expect(stages.export_gate).toBe("locked");
  });

  it("treats skipped as an explicit manual decision that unlocks the next stage", () => {
    const stages = stageMap({
      reviewStatus: "confirmed",
      qaGateStatus: "clear",
      storyboardDecision: "skipped",
      videoDecision: "skipped",
      exportDecision: "skipped",
    });

    expect(stages.storyboard_gate).toBe("complete");
    expect(stages.video_gate).toBe("complete");
    expect(stages.export_gate).toBe("complete");
  });

  it("returns local production gates in stable order", () => {
    expect(deriveLocalWorkflowStages({ reviewStatus: "no_step1", qaGateStatus: "clear" }).map((stage) => stage.id)).toEqual([
      "brief_gate",
      "script_gate",
      "asset_gate",
      "storyboard_gate",
      "video_gate",
      "export_gate",
    ]);
  });
});
