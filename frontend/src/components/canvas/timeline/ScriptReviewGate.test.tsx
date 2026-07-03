import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { ScriptReviewGate } from "./ScriptReviewGate";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import type { ClaudeDraftArtifact, ScriptReviewState } from "@/types";

const localWorkflowReviews = {
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
} satisfies ScriptReviewState["local_workflow_reviews"];

const localWorkflowArtifacts = {
  seedance_prompt: "",
  storyboard: { path: "", url: "", note: "", updated_at: null },
  video: { path: "", url: "", note: "", updated_at: null },
  export: { path: "", url: "", note: "", updated_at: null },
} satisfies ScriptReviewState["local_workflow_artifacts"];

function dramaState(overrides: Partial<ScriptReviewState> = {}): ScriptReviewState {
  return {
    episode: 1,
    content_mode: "drama",
    status: "pending_review",
    fingerprint: "fp1",
    confirmed_at: null,
    qa_findings: [],
    qa_summary: {
      info_count: 0,
      warn_count: 0,
      block_count: 0,
      gate_status: "clear",
      top_codes: [],
    },
    qa_gate_status: "clear",
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
    local_workflow_reviews: localWorkflowReviews,
    local_workflow_artifacts: localWorkflowArtifacts,
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
    qa_findings: [],
    qa_summary: {
      info_count: 0,
      warn_count: 0,
      block_count: 0,
      gate_status: "clear",
      top_codes: [],
    },
    qa_gate_status: "clear",
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
    local_workflow_reviews: localWorkflowReviews,
    local_workflow_artifacts: localWorkflowArtifacts,
    ...overrides,
  };
}

function claudeDraftArtifact(overrides: Partial<ClaudeDraftArtifact> = {}): ClaudeDraftArtifact {
  return {
    schema_version: 1,
    artifact_id: "1/20260703T000000000000Z-script_review_notes-test.json",
    intent: "script_review_notes",
    project_name: "p",
    episode: 1,
    created_at: "2026-07-03T00:00:00Z",
    status: "succeeded",
    context_hash: "sha256:test",
    policy: {
      permission_mode: "plan",
      tools: [],
      draft_only: true,
      env_scrubbed: true,
    },
    input_summary: {},
    output: {
      summary: "建议加强开场钩子。",
      findings: [{ code: "weak_hook", message: "第一镜缺少强刺激。" }],
      proposed_patch: null,
      raw_text: "",
    },
    ...overrides,
  };
}

describe("ScriptReviewGate", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders drama structured content with utterances and pending status", async () => {
    vi.spyOn(API, "getScriptReview").mockResolvedValue(dramaState());
    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByDisplayValue("你终于回来了。")).toBeInTheDocument());
    expect(screen.getByDisplayValue("阿离")).toBeInTheDocument();
    expect(screen.getByText("E1S01")).toBeInTheDocument();
    expect(screen.getByText("待审核")).toBeInTheDocument();
    expect(screen.getByText("短剧 QA 已通过")).toBeInTheDocument();
    expect(screen.getByText("确认并继续")).toBeInTheDocument();
  });

  it("renders blocking QA findings and prevents direct confirmation", async () => {
    const confirm = vi.spyOn(API, "confirmScriptReview").mockResolvedValue(dramaState());
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
            path: "$.scenes[0].props",
            evidence: "玉佩",
          },
        ],
      }),
    );

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("短剧 QA 检查")).toBeInTheDocument());
    expect(screen.getByText("阻断 1")).toBeInTheDocument();
    expect(screen.getByText("missing_prop_reference")).toBeInTheDocument();
    expect(screen.getByText("存在阻断项，需先修正后才能确认放行。")).toBeInTheDocument();
    expect(screen.getByText("确认并继续").closest("button")).toBeDisabled();
    expect(confirm).not.toHaveBeenCalled();
  });

  it("shows a draft-only Claude panel and creates a review draft without confirming gates", async () => {
    vi.spyOn(API, "getScriptReview").mockResolvedValue(dramaState());
    const createDraft = vi.spyOn(API, "createClaudeDraft").mockResolvedValue(claudeDraftArtifact());
    const confirm = vi.spyOn(API, "confirmScriptReview").mockResolvedValue(dramaState({ status: "confirmed" }));

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("Claude 草稿助手")).toBeInTheDocument());
    expect(screen.getByText("只创建草稿，不放行审核，不生成媒体。")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "向 Claude 请求审核草稿" }));

    await waitFor(() =>
      expect(createDraft).toHaveBeenCalledWith("p", {
        intent: "script_review_notes",
        episode: 1,
        instruction: "",
        timeout_seconds: 120,
      }),
    );
    expect(confirm).not.toHaveBeenCalled();
    expect(await screen.findByText("Claude 草稿摘要")).toBeInTheDocument();
    expect(screen.getByText("建议加强开场钩子。")).toBeInTheDocument();
    expect(screen.getByText("weak_hook")).toBeInTheDocument();
  });

  it("keeps blocked QA confirmation disabled after a Claude draft result", async () => {
    const blockedState = dramaState({
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
    });
    vi.spyOn(API, "getScriptReview").mockResolvedValue(blockedState);
    vi.spyOn(API, "createClaudeDraft").mockResolvedValue(claudeDraftArtifact());
    const confirm = vi.spyOn(API, "confirmScriptReview").mockResolvedValue(dramaState({ status: "confirmed" }));

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("存在阻断项，需先修正后才能确认放行。")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "确认并继续" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "向 Claude 请求审核草稿" }));

    await waitFor(() => expect(screen.getByText("Claude 草稿摘要")).toBeInTheDocument());
    expect(screen.getByText("存在阻断项，需先修正后才能确认放行。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认并继续" })).toBeDisabled();
    expect(confirm).not.toHaveBeenCalled();
  });

  it("does not show unlocked status for grandfathered confirmed content when QA blocks", async () => {
    vi.spyOn(API, "getScriptReview").mockResolvedValue(
      dramaState({
        status: "confirmed",
        confirmed_at: "2026-06-26T00:00:00Z",
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

    await waitFor(() => expect(screen.getByText("短剧 QA 检查")).toBeInTheDocument());
    expect(screen.getByText("待审核")).toBeInTheDocument();
    expect(screen.getByText("审阅内容后确认，放行视觉生成。")).toBeInTheDocument();
    expect(screen.queryByText("视觉生成已放行。再次编辑将重新进入审核。")).not.toBeInTheDocument();
    expect(screen.getByText("确认并继续").closest("button")).toBeDisabled();
  });

  it("saves dirty blocked content but does not confirm when QA remains blocked", async () => {
    const blockedState = dramaState({
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
    });
    vi.spyOn(API, "getScriptReview").mockResolvedValue(blockedState);
    const save = vi.spyOn(API, "saveScriptReviewContent").mockResolvedValue(blockedState);
    const confirm = vi.spyOn(API, "confirmScriptReview").mockResolvedValue(dramaState({ status: "confirmed" }));

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);
    await waitFor(() => expect(screen.getByDisplayValue("你终于回来了。")).toBeInTheDocument());

    fireEvent.change(screen.getByDisplayValue("你终于回来了。"), { target: { value: "我已经补了道具引用。" } });
    fireEvent.click(screen.getByText("确认并继续"));

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(confirm).not.toHaveBeenCalled();
  });

  it("shows warning QA findings while keeping human confirmation available", async () => {
    vi.spyOn(API, "getScriptReview").mockResolvedValue(
      dramaState({
        qa_gate_status: "warning",
        qa_summary: {
          info_count: 0,
          warn_count: 1,
          block_count: 0,
          gate_status: "warning",
          top_codes: ["weak_opening_hook"],
        },
        qa_findings: [
          {
            code: "weak_opening_hook",
            severity: "warn",
            message: "E1S01 开篇钩子信号偏弱。",
          },
        ],
      }),
    );

    render(<ScriptReviewGate projectName="p" episode={1} contentMode="drama" />);

    await waitFor(() => expect(screen.getByText("短剧 QA 检查")).toBeInTheDocument());
    expect(screen.getByText("警告 1")).toBeInTheDocument();
    expect(screen.getByText("weak_opening_hook")).toBeInTheDocument();
    expect(screen.getByText("确认并继续").closest("button")).not.toBeDisabled();
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
});
