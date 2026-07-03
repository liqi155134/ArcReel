import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { ScriptReviewGate } from "./ScriptReviewGate";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import type { ScriptReviewState } from "@/types";

function clearQaState(): Pick<ScriptReviewState, "qa_findings" | "qa_summary" | "qa_gate_status"> {
  return {
    qa_findings: [],
    qa_summary: { info_count: 0, warn_count: 0, block_count: 0, gate_status: "clear", top_codes: [] },
    qa_gate_status: "clear",
  };
}

function clearWorkflowState(): Pick<ScriptReviewState, "local_workflow_reviews"> {
  return {
    local_workflow_reviews: {
      storyboard_reviewed: false,
      storyboard_reviewed_at: null,
      storyboard_decision: "pending",
      storyboard_note: "",
      storyboard_checklist: {
        character_consistency: false,
        scene_prop_consistency: false,
        shot_count: false,
        prompt_quality: false,
      },
      video_reviewed: false,
      video_reviewed_at: null,
      video_decision: "pending",
      video_note: "",
      video_checklist: {
        motion_continuity: false,
        face_stability: false,
        duration_rhythm: false,
        first_last_frame: false,
      },
      export_reviewed: false,
      export_reviewed_at: null,
      export_decision: "pending",
      export_note: "",
      export_checklist: {
        subtitles_audio: false,
        aspect_cover: false,
        file_naming: false,
        final_playback: false,
      },
    },
  };
}

function clearArtifactState(): Pick<ScriptReviewState, "local_workflow_artifacts"> {
  return {
    local_workflow_artifacts: {
      seedance_prompt: "",
      storyboard: { path: "", url: "", note: "", updated_at: null },
      video: { path: "", url: "", note: "", updated_at: null },
      export: { path: "", url: "", note: "", updated_at: null },
    },
  };
}

function dramaState(overrides: Partial<ScriptReviewState> = {}): ScriptReviewState {
  return {
    episode: 1,
    content_mode: "drama",
    status: "pending_review",
    fingerprint: "fp1",
    confirmed_at: null,
    ...clearQaState(),
    ...clearWorkflowState(),
    ...clearArtifactState(),
    content: {
      title: "第一集",
      scenes: [
        {
          scene_id: "E1S01",
          duration_seconds: 8,
          segment_break: false,
          characters_in_scene: ["阿离"],
          scenes: [],
          props: [],
          scene_description: "雨夜，阿离立于屋檐下",
          utterances: [
            { kind: "voiceover", speaker: null, text: "三年后。" },
            { kind: "dialogue", speaker: "阿离", text: "你终于回来了。" },
          ],
          source_text: "三年后，阿离立于屋檐下：你终于回来了。",
        },
      ],
    },
    ...overrides,
  };
}

function narrationState(overrides: Partial<ScriptReviewState> = {}): ScriptReviewState {
  return {
    episode: 1,
    content_mode: "narration",
    status: "pending_review",
    fingerprint: "fp1",
    confirmed_at: null,
    ...clearQaState(),
    ...clearWorkflowState(),
    ...clearArtifactState(),
    content: {
      segments: [
        {
          segment_id: "E1S01",
          novel_text: "裴与出征后的第二年。",
          duration_seconds: 6,
          segment_break: false,
          characters_in_segment: ["裴与"],
          scenes: [],
          props: [],
        },
      ],
    },
    ...overrides,
  };
}

describe("ScriptReviewGate", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("renders drama structured content with utterances and pending status", async () => {
    vi.spyOn(API, "getScriptReview").mockResolvedValue(dramaState());
    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByDisplayValue("你终于回来了。")).toBeInTheDocument());
    expect(screen.getByDisplayValue("阿离")).toBeInTheDocument();
    expect(screen.getByText("E1S01")).toBeInTheDocument();
    expect(screen.getByText("待审核")).toBeInTheDocument();
    expect(screen.getByText("确认并继续")).toBeInTheDocument();
  });

  it("confirms and reflects the unlocked state", async () => {
    vi.spyOn(API, "getScriptReview").mockResolvedValue(dramaState());
    const confirm = vi
      .spyOn(API, "confirmScriptReview")
      .mockResolvedValue(dramaState({ status: "confirmed", confirmed_at: "2026-06-26T00:00:00Z" }));

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);
    await waitFor(() => expect(screen.getByText("确认并继续")).toBeInTheDocument());

    fireEvent.click(screen.getByText("确认并继续"));

    await waitFor(() => expect(confirm).toHaveBeenCalledWith("p", 1));
    await waitFor(() =>
      expect(screen.getByText("视觉生成已放行。再次编辑将重新进入审核。")).toBeInTheDocument(),
    );
  });

  it("edits content, surfaces save, and persists the edited intermediate", async () => {
    vi.spyOn(API, "getScriptReview").mockResolvedValue(dramaState());
    const save = vi.spyOn(API, "saveScriptReviewContent").mockResolvedValue(dramaState());

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);
    await waitFor(() => expect(screen.getByDisplayValue("你终于回来了。")).toBeInTheDocument());

    fireEvent.change(screen.getByDisplayValue("你终于回来了。"), { target: { value: "你怎么才回来。" } });
    // 编辑后出现保存按钮
    const saveBtn = await screen.findByText("保存");
    fireEvent.click(saveBtn);

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    const [, , savedContent] = save.mock.calls[0];
    expect(savedContent).toMatchObject({
      scenes: [{ utterances: [{ text: "三年后。" }, { text: "你怎么才回来。" }] }],
    });
  });

  it("renders narration novel_text as editable", async () => {
    vi.spyOn(API, "getScriptReview").mockResolvedValue(narrationState());
    render(<ScriptReviewGate projectName="p" episode={1} contentMode="narration" />);

    await waitFor(() => expect(screen.getByDisplayValue("裴与出征后的第二年。")).toBeInTheDocument());
    expect(screen.getByText("E1S01")).toBeInTheDocument();
  });

  it("adopts externally edited (agent) content on refetch when the user has no edits", async () => {
    const edited = dramaState();
    (edited.content as { scenes: { utterances: { text: string }[] }[] }).scenes[0].utterances[1].text =
      "agent 改写后的台词";
    const get = vi
      .spyOn(API, "getScriptReview")
      .mockResolvedValueOnce(dramaState())
      .mockResolvedValueOnce(edited);

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);
    await waitFor(() => expect(screen.getByDisplayValue("你终于回来了。")).toBeInTheDocument());

    // 模拟 agent 在外部改了 step1 → revision 变 → 触发重新拉取
    act(() => {
      useAppStore.getState().invalidateEntities(["draft:episode_1_step1"]);
    });

    await waitFor(() => expect(screen.getByDisplayValue("agent 改写后的台词")).toBeInTheDocument());
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("preserves the user's unsaved edits when an external refetch arrives", async () => {
    const serverEdited = dramaState();
    (serverEdited.content as { scenes: { utterances: { text: string }[] }[] }).scenes[0].utterances[1].text =
      "服务端覆盖文案";
    const get = vi
      .spyOn(API, "getScriptReview")
      .mockResolvedValueOnce(dramaState())
      .mockResolvedValueOnce(serverEdited);

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);
    await waitFor(() => expect(screen.getByDisplayValue("你终于回来了。")).toBeInTheDocument());

    // 用户本地编辑，尚未保存
    fireEvent.change(screen.getByDisplayValue("你终于回来了。"), { target: { value: "我的本地编辑" } });
    await screen.findByText("保存");

    // 外部刷新到来（agent 改 step1 → revision 变）→ 应保留用户草稿、不被服务端内容覆盖
    act(() => {
      useAppStore.getState().invalidateEntities(["draft:episode_1_step1"]);
    });

    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(screen.getByDisplayValue("我的本地编辑")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("服务端覆盖文案")).not.toBeInTheDocument();
  });

  it("shows an empty state when there is no step1 content", async () => {
    vi.spyOn(API, "getScriptReview").mockResolvedValue(
      dramaState({ status: "no_step1", content: null, fingerprint: null }),
    );
    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);
    await waitFor(() => expect(screen.getByText("暂无预处理内容")).toBeInTheDocument());
  });

  it("renders a load-error state distinct from the empty state", async () => {
    vi.spyOn(API, "getScriptReview").mockRejectedValue(new Error("网络异常"));
    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("无法加载预处理内容")).toBeInTheDocument());
    // 错误态展示服务端错误信息与重试入口，且不与空态文案混淆。
    expect(screen.getByText("网络异常")).toBeInTheDocument();
    expect(screen.getByText("重试")).toBeInTheDocument();
    expect(screen.queryByText("暂无预处理内容")).not.toBeInTheDocument();
  });

  it("surfaces an error with retry when a refetch fails after an empty state", async () => {
    const get = vi
      .spyOn(API, "getScriptReview")
      .mockResolvedValueOnce(dramaState({ status: "no_step1", content: null, fingerprint: null }))
      .mockRejectedValue(new Error("刷新失败"));
    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);
    await waitFor(() => expect(screen.getByText("暂无预处理内容")).toBeInTheDocument());

    // 空态无真实内容可保留：revision 静默刷新失败应进错误态（区别于空态）并给重试，不滞留在过时空态。
    act(() => {
      useAppStore.getState().invalidateEntities(["draft:episode_1_step1"]);
    });

    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(screen.getByText("无法加载预处理内容")).toBeInTheDocument();
    expect(screen.getByText("重试")).toBeInTheDocument();
    expect(screen.queryByText("暂无预处理内容")).not.toBeInTheDocument();
  });

  it("keeps existing content when a silent refetch fails", async () => {
    const get = vi
      .spyOn(API, "getScriptReview")
      .mockResolvedValueOnce(dramaState())
      .mockRejectedValue(new Error("刷新失败"));
    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);
    await waitFor(() => expect(screen.getByDisplayValue("你终于回来了。")).toBeInTheDocument());

    // revision 触发静默刷新失败：应保留已加载内容，不闪错误态 / 空态。
    act(() => {
      useAppStore.getState().invalidateEntities(["draft:episode_1_step1"]);
    });

    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(screen.getByDisplayValue("你终于回来了。")).toBeInTheDocument();
    expect(screen.queryByText("无法加载预处理内容")).not.toBeInTheDocument();
    expect(screen.queryByText("暂无预处理内容")).not.toBeInTheDocument();
  });

  it("retries after a load error and recovers to normal content", async () => {
    const get = vi
      .spyOn(API, "getScriptReview")
      .mockRejectedValueOnce(new Error("网络异常"))
      .mockResolvedValue(dramaState());
    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("重试")).toBeInTheDocument());

    fireEvent.click(screen.getByText("重试"));

    await waitFor(() => expect(screen.getByDisplayValue("你终于回来了。")).toBeInTheDocument());
    expect(screen.queryByText("无法加载预处理内容")).not.toBeInTheDocument();
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("records storyboard human review decision and note", async () => {
    const confirmed = dramaState({ status: "confirmed", confirmed_at: "2026-07-03T00:00:00Z" });
    const needsChanges = dramaState({
      status: "confirmed",
      confirmed_at: "2026-07-03T00:00:00Z",
      local_workflow_reviews: {
        ...clearWorkflowState().local_workflow_reviews,
        storyboard_decision: "needs_changes",
        storyboard_note: "人物脸不一致，重出第 3 镜",
      },
    });
    vi.spyOn(API, "getScriptReview").mockResolvedValue(confirmed);
    const setGate = vi.spyOn(API, "setScriptReviewWorkflowGate").mockResolvedValue(needsChanges);

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("标记分镜图已审核")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("分镜图人工审核备注"), {
      target: { value: "人物脸不一致，重出第 3 镜" },
    });
    fireEvent.click(screen.getByText("需要修改"));

    await waitFor(() =>
      expect(setGate).toHaveBeenCalledWith("p", 1, "storyboard", false, {
        decision: "needs_changes",
        note: "人物脸不一致，重出第 3 镜",
        checklist: {
          character_consistency: false,
          scene_prop_consistency: false,
          shot_count: false,
          prompt_quality: false,
        },
      }),
    );
    await waitFor(() => expect(screen.getAllByText(/人物脸不一致，重出第 3 镜/).length).toBeGreaterThan(0));
  });

  it("submits storyboard manual checklist values with the review decision", async () => {
    const confirmed = dramaState({ status: "confirmed", confirmed_at: "2026-07-03T00:00:00Z" });
    const needsChanges = dramaState({
      status: "confirmed",
      confirmed_at: "2026-07-03T00:00:00Z",
      local_workflow_reviews: {
        ...clearWorkflowState().local_workflow_reviews,
        storyboard_decision: "needs_changes",
        storyboard_note: "镜头数量不够，补两个反应镜头。",
        storyboard_checklist: {
          character_consistency: true,
          scene_prop_consistency: true,
          shot_count: false,
          prompt_quality: true,
        },
      },
    });
    vi.spyOn(API, "getScriptReview").mockResolvedValue(confirmed);
    const setGate = vi.spyOn(API, "setScriptReviewWorkflowGate").mockResolvedValue(needsChanges);

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByLabelText("角色一致性")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("角色一致性"));
    fireEvent.click(screen.getByLabelText("场景/道具一致性"));
    fireEvent.click(screen.getByLabelText("提示词质量"));
    fireEvent.change(screen.getByLabelText("分镜图人工审核备注"), {
      target: { value: "镜头数量不够，补两个反应镜头。" },
    });
    fireEvent.click(screen.getByText("需要修改"));

    await waitFor(() =>
      expect(setGate).toHaveBeenCalledWith("p", 1, "storyboard", false, {
        decision: "needs_changes",
        note: "镜头数量不够，补两个反应镜头。",
        checklist: {
          character_consistency: true,
          scene_prop_consistency: true,
          shot_count: false,
          prompt_quality: true,
        },
      }),
    );
    await waitFor(() => expect(screen.getAllByText(/镜头数量不够/).length).toBeGreaterThan(0));
  });

  it("shows the current rework blocker and lets the reviewer mark it fixed for re-review", async () => {
    const blocked = dramaState({
      status: "confirmed",
      confirmed_at: "2026-07-03T00:00:00Z",
      local_workflow_reviews: {
        ...clearWorkflowState().local_workflow_reviews,
        storyboard_decision: "needs_changes",
        storyboard_note: "镜头数量不够，补两个反应镜头。",
        storyboard_checklist: {
          character_consistency: true,
          scene_prop_consistency: true,
          shot_count: false,
          prompt_quality: true,
        },
      },
    });
    const pendingAgain = dramaState({
      status: "confirmed",
      confirmed_at: "2026-07-03T00:00:00Z",
      local_workflow_reviews: {
        ...blocked.local_workflow_reviews,
        storyboard_decision: "pending",
        storyboard_note: "",
      },
    });
    vi.spyOn(API, "getScriptReview").mockResolvedValue(blocked);
    const setGate = vi.spyOn(API, "setScriptReviewWorkflowGate").mockResolvedValue(pendingAgain);

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("当前卡点：分镜图审核")).toBeInTheDocument());
    expect(screen.getByText("镜头数量不够，补两个反应镜头。")).toBeInTheDocument();
    expect(screen.getByText("未通过：镜头数量")).toBeInTheDocument();
    expect(screen.getByLabelText("视频生成：锁定")).toBeInTheDocument();

    fireEvent.click(screen.getByText("标记已修复，重新审核"));

    await waitFor(() =>
      expect(setGate).toHaveBeenCalledWith("p", 1, "storyboard", false, {
        decision: "pending",
        note: "",
        checklist: {
          character_consistency: true,
          scene_prop_consistency: true,
          shot_count: false,
          prompt_quality: true,
        },
      }),
    );
    await waitFor(() => expect(screen.queryByText("当前卡点：分镜图审核")).not.toBeInTheDocument());
  });

  it("exports a manual review package with script content, review state, and imported prompt", async () => {
    const createObjectURL = vi.fn((_blob: Blob) => "blob:manual-review-package");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    vi.spyOn(API, "getScriptReview").mockResolvedValue(
      dramaState({ status: "confirmed", confirmed_at: "2026-07-03T00:00:00Z" }),
    );

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("导入 Prompt")).toBeInTheDocument());
    fireEvent.click(screen.getByText("导入 Prompt"));
    fireEvent.change(screen.getByLabelText("Seedance Prompt"), {
      target: { value: "E1S01: 阿离雨夜屋檐下近景，电影感。" },
    });
    fireEvent.click(screen.getByText("导出审核包"));

    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
    const blob = createObjectURL.mock.calls[0][0] as Blob;
    const exported = JSON.parse(await blob.text()) as {
      schema: string;
      project_name: string;
      episode: number;
      seedance_prompt: string;
      content: { scenes: Array<{ scene_id: string }> };
      local_workflow_reviews: ScriptReviewState["local_workflow_reviews"];
      local_workflow_artifacts: ScriptReviewState["local_workflow_artifacts"];
    };
    expect(exported.schema).toBe("arcreel.local_manual_review_package.v1");
    expect(exported.project_name).toBe("p");
    expect(exported.episode).toBe(1);
    expect(exported.seedance_prompt).toBe("E1S01: 阿离雨夜屋檐下近景，电影感。");
    expect(exported.local_workflow_artifacts.seedance_prompt).toBe("E1S01: 阿离雨夜屋檐下近景，电影感。");
    expect(exported.content.scenes[0].scene_id).toBe("E1S01");
    expect(exported.local_workflow_reviews.storyboard_decision).toBe("pending");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:manual-review-package");
  });

  it("saves Seedance prompt and manual artifact ledger entries", async () => {
    const confirmed = dramaState({ status: "confirmed", confirmed_at: "2026-07-03T00:00:00Z" });
    const saved = dramaState({
      status: "confirmed",
      confirmed_at: "2026-07-03T00:00:00Z",
      local_workflow_artifacts: {
        ...clearArtifactState().local_workflow_artifacts,
        seedance_prompt: "E1S01: 阿离雨夜屋檐下近景，电影感。",
        storyboard: {
          path: "storyboards/e1s01.png",
          url: "",
          note: "人工筛选第 2 张。",
          updated_at: "2026-07-03T00:05:00Z",
        },
      },
    });
    vi.spyOn(API, "getScriptReview").mockResolvedValue(confirmed);
    const setArtifacts = vi.spyOn(API, "setScriptReviewWorkflowArtifacts").mockResolvedValue(saved);

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("导入 Prompt")).toBeInTheDocument());
    fireEvent.click(screen.getByText("导入 Prompt"));
    fireEvent.change(screen.getByLabelText("Seedance Prompt"), {
      target: { value: "E1S01: 阿离雨夜屋檐下近景，电影感。" },
    });
    fireEvent.change(screen.getByLabelText("分镜图文件/链接"), {
      target: { value: "storyboards/e1s01.png" },
    });
    fireEvent.change(screen.getByLabelText("分镜图备注"), {
      target: { value: "人工筛选第 2 张。" },
    });
    fireEvent.click(screen.getByText("保存生产台账"));

    await waitFor(() =>
      expect(setArtifacts).toHaveBeenCalledWith("p", 1, {
        seedance_prompt: "E1S01: 阿离雨夜屋檐下近景，电影感。",
        artifacts: {
          storyboard: { path: "storyboards/e1s01.png", url: "", note: "人工筛选第 2 张。" },
          video: { path: "", url: "", note: "" },
          export: { path: "", url: "", note: "" },
        },
      }),
    );
    await waitFor(() => expect(screen.getByDisplayValue("storyboards/e1s01.png")).toBeInTheDocument());
  });

  it("imports pasted manual review package JSON into the artifact ledger", async () => {
    const imported = dramaState({
      status: "confirmed",
      confirmed_at: "2026-07-03T00:00:00Z",
      local_workflow_artifacts: {
        ...clearArtifactState().local_workflow_artifacts,
        seedance_prompt: "E1S01: 导入后的 Seedance prompt。",
        storyboard: {
          path: "storyboards/imported.png",
          url: "",
          note: "从审核包恢复。",
          updated_at: "2026-07-03T00:06:00Z",
        },
      },
    });
    vi.spyOn(API, "getScriptReview").mockResolvedValue(dramaState({ status: "confirmed" }));
    const setArtifacts = vi.spyOn(API, "setScriptReviewWorkflowArtifacts").mockResolvedValue(imported);

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("导入 Prompt")).toBeInTheDocument());
    fireEvent.click(screen.getByText("导入 Prompt"));
    fireEvent.change(screen.getByLabelText("审核包 JSON"), {
      target: {
        value: JSON.stringify({
          schema: "arcreel.local_manual_review_package.v1",
          local_workflow_artifacts: imported.local_workflow_artifacts,
        }),
      },
    });
    fireEvent.click(screen.getByText("应用审核包"));

    await waitFor(() =>
      expect(setArtifacts).toHaveBeenCalledWith("p", 1, {
        seedance_prompt: "E1S01: 导入后的 Seedance prompt。",
        artifacts: {
          storyboard: { path: "storyboards/imported.png", url: "", note: "从审核包恢复。" },
          video: { path: "", url: "", note: "" },
          export: { path: "", url: "", note: "" },
        },
      }),
    );
  });

  it("copies a rework brief with blocker, failed checklist, and imported prompt", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    vi.spyOn(API, "getScriptReview").mockResolvedValue(
      dramaState({
        status: "confirmed",
        confirmed_at: "2026-07-03T00:00:00Z",
        local_workflow_reviews: {
          ...clearWorkflowState().local_workflow_reviews,
          storyboard_decision: "needs_changes",
          storyboard_note: "镜头数量不够，补两个反应镜头。",
          storyboard_checklist: {
            character_consistency: true,
            scene_prop_consistency: true,
            shot_count: false,
            prompt_quality: true,
          },
        },
      }),
    );

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("复制返工说明")).toBeInTheDocument());
    fireEvent.click(screen.getByText("导入 Prompt"));
    fireEvent.change(screen.getByLabelText("Seedance Prompt"), {
      target: { value: "E1S01: 需要补反应镜头。" },
    });
    fireEvent.click(screen.getByText("复制返工说明"));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const copied = writeText.mock.calls[0][0] as string;
    expect(copied).toContain("当前卡点：分镜图审核");
    expect(copied).toContain("镜头数量不够，补两个反应镜头。");
    expect(copied).toContain("未通过：镜头数量");
    expect(copied).toContain("Seedance Prompt：E1S01: 需要补反应镜头。");
  });

  it("marks storyboard review manually after script confirmation", async () => {
    const confirmed = dramaState({ status: "confirmed", confirmed_at: "2026-07-03T00:00:00Z" });
    const reviewed = dramaState({
      status: "confirmed",
      confirmed_at: "2026-07-03T00:00:00Z",
      local_workflow_reviews: {
        ...clearWorkflowState().local_workflow_reviews,
        storyboard_reviewed: true,
        storyboard_reviewed_at: "2026-07-03T00:01:00Z",
      },
    });
    vi.spyOn(API, "getScriptReview").mockResolvedValue(confirmed);
    const setGate = vi.spyOn(API, "setScriptReviewWorkflowGate").mockResolvedValue(reviewed);

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("标记分镜图已审核")).toBeInTheDocument());
    fireEvent.click(screen.getByText("标记分镜图已审核"));

    await waitFor(() =>
      expect(setGate).toHaveBeenCalledWith("p", 1, "storyboard", true, {
        decision: "approved",
        note: "",
        checklist: {
          character_consistency: false,
          scene_prop_consistency: false,
          shot_count: false,
          prompt_quality: false,
        },
      }),
    );
    await waitFor(() => expect(screen.getByText("分镜图已审核")).toBeInTheDocument());
    expect(screen.getByLabelText("视频生成：就绪")).toBeInTheDocument();
  });

  it("renders reviewed storyboard gate without the manual mark action", async () => {
    vi.spyOn(API, "getScriptReview").mockResolvedValue(
      dramaState({
        status: "confirmed",
        confirmed_at: "2026-07-03T00:00:00Z",
        local_workflow_reviews: {
          ...clearWorkflowState().local_workflow_reviews,
          storyboard_reviewed: true,
          storyboard_reviewed_at: "2026-07-03T00:01:00Z",
        },
      }),
    );

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("分镜图已审核")).toBeInTheDocument());
    expect(screen.queryByText("标记分镜图已审核")).not.toBeInTheDocument();
    expect(screen.getByLabelText("分镜图审核：完成")).toBeInTheDocument();
  });


  it("marks video and export reviews manually after upstream gates are reviewed", async () => {
    const readyForVideo = dramaState({
      status: "confirmed",
      confirmed_at: "2026-07-03T00:00:00Z",
      local_workflow_reviews: {
        ...clearWorkflowState().local_workflow_reviews,
        storyboard_reviewed: true,
        storyboard_reviewed_at: "2026-07-03T00:01:00Z",
      },
    });
    const readyForExport = dramaState({
      status: "confirmed",
      confirmed_at: "2026-07-03T00:00:00Z",
      local_workflow_reviews: {
        ...clearWorkflowState().local_workflow_reviews,
        storyboard_reviewed: true,
        storyboard_reviewed_at: "2026-07-03T00:01:00Z",
        video_reviewed: true,
        video_reviewed_at: "2026-07-03T00:02:00Z",
      },
    });
    const fullyReviewed = dramaState({
      status: "confirmed",
      confirmed_at: "2026-07-03T00:00:00Z",
      local_workflow_reviews: {
        ...readyForExport.local_workflow_reviews,
        export_reviewed: true,
        export_reviewed_at: "2026-07-03T00:03:00Z",
      },
    });
    vi.spyOn(API, "getScriptReview").mockResolvedValue(readyForVideo);
    const setGate = vi
      .spyOn(API, "setScriptReviewWorkflowGate")
      .mockResolvedValueOnce(readyForExport)
      .mockResolvedValueOnce(fullyReviewed);

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("标记视频已审核")).toBeInTheDocument());
    fireEvent.click(screen.getByText("标记视频已审核"));

    await waitFor(() =>
      expect(setGate).toHaveBeenCalledWith("p", 1, "video", true, {
        decision: "approved",
        note: "",
        checklist: {
          motion_continuity: false,
          face_stability: false,
          duration_rhythm: false,
          first_last_frame: false,
        },
      }),
    );
    await waitFor(() => expect(screen.getByText("视频已审核")).toBeInTheDocument());
    expect(screen.getByLabelText("导出检查：就绪")).toBeInTheDocument();

    fireEvent.click(screen.getByText("标记导出已审核"));

    await waitFor(() =>
      expect(setGate).toHaveBeenCalledWith("p", 1, "export", true, {
        decision: "approved",
        note: "",
        checklist: {
          subtitles_audio: false,
          aspect_cover: false,
          file_naming: false,
          final_playback: false,
        },
      }),
    );
    await waitFor(() => expect(screen.getByText("导出已审核")).toBeInTheDocument());
    expect(screen.getByLabelText("导出检查：完成")).toBeInTheDocument();
  });

  it("renders local workflow overview with blocked script gate and locked video stage", async () => {
    vi.spyOn(API, "getScriptReview").mockResolvedValue(
      dramaState({
        qa_gate_status: "blocked",
        qa_summary: {
          info_count: 0,
          warn_count: 0,
          block_count: 1,
          gate_status: "blocked",
          top_codes: ["missing_prop_reference"],
        },
        qa_findings: [
          {
            code: "missing_prop_reference",
            severity: "block",
            message: "E1S01 引用了未登记的 props 资产。",
          },
        ],
      }),
    );

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("本地生产流程")).toBeInTheDocument());
    expect(screen.getByText("脚本审核")).toBeInTheDocument();
    expect(screen.getByLabelText("脚本审核：阻塞")).toBeInTheDocument();
    expect(screen.getByText("视频生成")).toBeInTheDocument();
    expect(screen.getByLabelText("视频生成：锁定")).toBeInTheDocument();
  });

  it("renders QA findings and disables confirm for deterministic blocks", async () => {
    const confirm = vi.spyOn(API, "confirmScriptReview").mockResolvedValue(dramaState());
    vi.spyOn(API, "getScriptReview").mockResolvedValue(
      dramaState({
        qa_gate_status: "blocked",
        qa_summary: {
          info_count: 0,
          warn_count: 1,
          block_count: 1,
          gate_status: "blocked",
          top_codes: ["missing_prop_reference"],
        },
        qa_findings: [
          {
            code: "missing_prop_reference",
            severity: "block",
            message: "E1S01 引用了未登记的 props 资产。",
            path: "$.scenes[0].props",
            evidence: "玉佩",
            recommendation: "先登记道具。",
          },
          {
            code: "weak_opening_hook",
            severity: "warn",
            message: "开篇钩子偏弱。",
            recommendation: "加强危机。",
          },
        ],
      }),
    );

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("短剧 QA 检查")).toBeInTheDocument());
    expect(screen.getByText("missing_prop_reference")).toBeInTheDocument();
    expect(screen.getByText("玉佩")).toBeInTheDocument();
    expect(screen.getByText(/存在确定性阻塞项/)).toBeInTheDocument();
    const confirmButton = screen.getByRole("button", { name: /确认并继续/ });
    expect(confirmButton).toBeDisabled();
    fireEvent.click(confirmButton);
    expect(confirm).not.toHaveBeenCalled();
  });
});
