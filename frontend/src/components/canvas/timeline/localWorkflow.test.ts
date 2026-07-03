import { describe, expect, it } from "vitest";
import { deriveLocalWorkflowStages } from "./localWorkflow";

function stageMap(input: Parameters<typeof deriveLocalWorkflowStages>[0]) {
  return Object.fromEntries(deriveLocalWorkflowStages(input).map((stage) => [stage.id, stage]));
}

describe("deriveLocalWorkflowStages", () => {
  it("blocks downstream video work when deterministic script QA is blocked", () => {
    const stages = stageMap({ reviewStatus: "pending_review", qaGateStatus: "blocked" });

    expect(stages.script_gate.status).toBe("blocked");
    expect(stages.storyboard_gate.status).toBe("locked");
    expect(stages.video_gate.status).toBe("locked");
    expect(stages.export_gate.status).toBe("locked");
  });

  it("marks storyboard review ready and video locked when script QA has warnings only", () => {
    const stages = stageMap({ reviewStatus: "pending_review", qaGateStatus: "warning" });

    expect(stages.script_gate.status).toBe("warning");
    expect(stages.asset_gate.status).toBe("ready");
    expect(stages.storyboard_gate.status).toBe("ready");
    expect(stages.video_gate.status).toBe("locked");
  });

  it("unlocks video generation after script confirmation and storyboard review", () => {
    const stages = stageMap({ reviewStatus: "confirmed", qaGateStatus: "clear", storyboardReviewed: true });

    expect(stages.script_gate.status).toBe("complete");
    expect(stages.storyboard_gate.status).toBe("complete");
    expect(stages.video_gate.status).toBe("ready");
    expect(stages.export_gate.status).toBe("locked");
  });

  it("returns the six local-production gates in order", () => {
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
