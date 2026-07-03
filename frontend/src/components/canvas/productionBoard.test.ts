import { describe, expect, it } from "vitest";
import type { EpisodeMeta, ScriptReviewState } from "@/types";
import {
  buildEpisodeProductionCsv,
  deriveEpisodeProductionRows,
  summarizeEpisodeProductionRows,
} from "./productionBoard";

function episode(episodeNo: number, title: string): EpisodeMeta {
  return {
    episode: episodeNo,
    title,
    script_file: `scripts/episode_${episodeNo}.json`,
    script_status: "generated",
    status: "in_production",
  };
}

function reviewState(overrides: Partial<ScriptReviewState> = {}): ScriptReviewState {
  return {
    episode: 1,
    content_mode: "drama",
    status: "confirmed",
    fingerprint: "fp",
    confirmed_at: "2026-07-03T00:00:00Z",
    content: null,
    qa_findings: [],
    qa_summary: { info_count: 0, warn_count: 0, block_count: 0, gate_status: "clear", top_codes: [] },
    qa_gate_status: "clear",
    local_workflow_reviews: {
      storyboard_reviewed: false,
      storyboard_reviewed_at: null,
      storyboard_decision: "pending",
      storyboard_note: "",
      storyboard_checklist: {},
      video_reviewed: false,
      video_reviewed_at: null,
      video_decision: "pending",
      video_note: "",
      video_checklist: {},
      export_reviewed: false,
      export_reviewed_at: null,
      export_decision: "pending",
      export_note: "",
      export_checklist: {},
    },
    local_workflow_artifacts: {
      seedance_prompt: "E1S01 prompt",
      storyboard: { path: "storyboards/e1.png", url: "", note: "", updated_at: null },
      video: { path: "videos/e1.mp4", url: "", note: "", updated_at: null },
      export: { path: "exports/e1.mp4", url: "", note: "", updated_at: null },
    },
    ...overrides,
  };
}

describe("episodeProductionBoard", () => {
  it("derives QA blockers, rework blockers, missing prompts, and missing artifact issues", () => {
    const rows = deriveEpisodeProductionRows(
      [episode(1, "雨夜真相"), episode(2, "屋檐返工"), episode(3, "成片检查")],
      {
        1: reviewState({
          episode: 1,
          status: "pending_review",
          qa_gate_status: "blocked",
          qa_summary: { info_count: 0, warn_count: 0, block_count: 1, gate_status: "blocked", top_codes: ["missing_prop_reference"] },
          qa_findings: [{ code: "missing_prop_reference", severity: "block", message: "缺少道具" }],
        }),
        2: reviewState({
          episode: 2,
          local_workflow_reviews: {
            ...reviewState().local_workflow_reviews,
            storyboard_decision: "needs_changes",
            storyboard_note: "补两个反应镜头。",
          },
        }),
        3: reviewState({
          episode: 3,
          local_workflow_reviews: {
            ...reviewState().local_workflow_reviews,
            storyboard_reviewed: true,
            storyboard_decision: "approved",
            video_reviewed: true,
            video_decision: "approved",
            export_reviewed: true,
            export_decision: "approved",
          },
          local_workflow_artifacts: {
            seedance_prompt: "",
            storyboard: { path: "storyboards/e3.png", url: "", note: "", updated_at: null },
            video: { path: "", url: "", note: "", updated_at: null },
            export: { path: "", url: "", note: "", updated_at: null },
          },
        }),
      },
    );

    expect(rows[0]).toMatchObject({ episode: 1, script: "blocked" });
    expect(rows[0].issues).toContain("qa_blocked");
    expect(rows[1]).toMatchObject({ episode: 2, storyboard: "needs_changes", video: "locked", export: "locked" });
    expect(rows[1].issues).toContain("storyboard_rework");
    expect(rows[2]).toMatchObject({ episode: 3, video: "missing_artifact", export: "missing_artifact" });
    expect(rows[2].issues).toEqual(expect.arrayContaining(["missing_prompt", "missing_video_artifact", "missing_export_artifact"]));

    expect(summarizeEpisodeProductionRows(rows)).toEqual({
      total: 3,
      qaBlocked: 1,
      rework: 1,
      missingPrompt: 1,
      missingVideo: 1,
      missingExport: 1,
    });
  });

  it("builds a CSV production checklist with stage and issue labels", () => {
    const rows = deriveEpisodeProductionRows([episode(1, "雨夜真相")], {
      1: reviewState({
        episode: 1,
        qa_gate_status: "blocked",
        qa_summary: { info_count: 0, warn_count: 0, block_count: 1, gate_status: "blocked", top_codes: ["missing_prop_reference"] },
      }),
    });

    const csv = buildEpisodeProductionCsv(rows);

    expect(csv).toContain("episode,title,script,storyboard,video,export,issues");
    expect(csv).toContain("1,雨夜真相,QA阻塞");
    expect(csv).toContain("QA阻塞");
  });
});
