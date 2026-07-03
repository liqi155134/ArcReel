import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { OverviewCanvas } from "./OverviewCanvas";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import type { ProjectData, ScriptReviewState } from "@/types";

vi.mock("./WelcomeCanvas", () => ({
  WelcomeCanvas: () => <div data-testid="welcome-canvas">welcome</div>,
}));

vi.mock("./AdInitCanvas", () => ({
  AdInitCanvas: () => <div data-testid="ad-init-canvas">ad-init</div>,
}));

function makeProjectData(overrides: Partial<ProjectData> = {}): ProjectData {
  return {
    title: "Demo",
    content_mode: "narration",
    style: "Anime",
    style_description: "old description",
    overview: {
      synopsis: "summary",
      genre: "fantasy",
      theme: "growth",
      world_setting: "palace",
    },
    episodes: [{ episode: 1, title: "EP1", script_file: "scripts/episode_1.json" }],
    characters: {},
    scenes: {},
    props: {},
    ...overrides,
  };
}

function productionReviewState(overrides: Partial<ScriptReviewState> = {}): ScriptReviewState {
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

describe("OverviewCanvas", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    useProjectsStore.setState(useProjectsStore.getInitialState(), true);
    vi.restoreAllMocks();
    vi.stubGlobal("confirm", vi.fn(() => true));
  });

  it("renders the project title and content mode", () => {
    render(<OverviewCanvas projectName="demo" projectData={makeProjectData()} />);
    expect(screen.getByText("Demo")).toBeInTheDocument();
  });

  it("shows welcome canvas when there is no overview and no episodes", () => {
    render(
      <OverviewCanvas
        projectName="demo"
        projectData={makeProjectData({ overview: undefined, episodes: [] })}
      />,
    );
    expect(screen.getByTestId("welcome-canvas")).toBeInTheDocument();
  });

  it("regenerates overview on button click", async () => {
    vi.spyOn(API, "generateOverview").mockResolvedValue(undefined as never);
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: makeProjectData(),
      scripts: {},
    });

    render(<OverviewCanvas projectName="demo" projectData={makeProjectData()} />);

    fireEvent.click(screen.getByRole("button", { name: "重新生成" }));
    await waitFor(() => {
      expect(API.generateOverview).toHaveBeenCalledWith("demo");
    });
  }, 10_000);

  it("edits the four overview fields and saves via API.updateOverview", async () => {
    vi.spyOn(API, "updateOverview").mockResolvedValue(undefined as never);
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: makeProjectData(),
      scripts: {},
    });

    render(<OverviewCanvas projectName="demo" projectData={makeProjectData()} />);

    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    fireEvent.change(screen.getByLabelText("故事梗概"), { target: { value: "新梗概" } });
    fireEvent.change(screen.getByLabelText("世界观设定"), { target: { value: "新世界观" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(API.updateOverview).toHaveBeenCalledWith(
        "demo",
        expect.objectContaining({ synopsis: "新梗概", world_setting: "新世界观" }),
      );
    });
  });

  it("reverts overview edits on cancel", () => {
    render(<OverviewCanvas projectName="demo" projectData={makeProjectData()} />);

    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    fireEvent.change(screen.getByLabelText("故事梗概"), { target: { value: "临时改动" } });
    fireEvent.click(screen.getByRole("button", { name: "取消" }));

    // 退出编辑：表单消失，显示原 synopsis 文本
    expect(screen.queryByLabelText("故事梗概")).toBeNull();
    expect(screen.getByText("summary")).toBeInTheDocument();
  });

  it("offers a create-overview entry when overview is absent but episodes exist", () => {
    render(
      <OverviewCanvas
        projectName="demo"
        projectData={makeProjectData({ overview: undefined })}
      />,
    );
    expect(screen.getByRole("button", { name: "创建概述" })).toBeInTheDocument();
  });

  it("renders a project-level production board with blockers, rework, and missing prompt issues", async () => {
    vi.spyOn(API, "getScriptReview").mockImplementation(async (_project, episode) =>
      episode === 1
        ? productionReviewState({
            episode: 1,
            status: "pending_review",
            qa_gate_status: "blocked",
            qa_summary: {
              info_count: 0,
              warn_count: 0,
              block_count: 1,
              gate_status: "blocked",
              top_codes: ["missing_prop_reference"],
            },
          })
        : productionReviewState({
            episode: 2,
            local_workflow_reviews: {
              ...productionReviewState().local_workflow_reviews,
              storyboard_decision: "needs_changes",
              storyboard_note: "补两个反应镜头。",
            },
            local_workflow_artifacts: {
              ...productionReviewState().local_workflow_artifacts,
              seedance_prompt: "",
            },
          }),
    );

    render(
      <OverviewCanvas
        projectName="demo"
        projectData={makeProjectData({
          content_mode: "drama",
          episodes: [
            { episode: 1, title: "雨夜真相", script_file: "scripts/episode_1.json" },
            { episode: 2, title: "屋檐返工", script_file: "scripts/episode_2.json" },
          ],
        })}
      />,
    );

    await waitFor(() => expect(screen.getByText("短剧生产看板")).toBeInTheDocument());
    expect(screen.getByText("QA 阻塞")).toBeInTheDocument();
    expect(screen.getByText("返工卡点")).toBeInTheDocument();
    expect(screen.getAllByText("缺 Prompt").length).toBeGreaterThan(0);
    expect(screen.getAllByText("雨夜真相").length).toBeGreaterThan(0);
    expect(screen.getAllByText("屋檐返工").length).toBeGreaterThan(0);
    expect(screen.getAllByText("QA阻塞").length).toBeGreaterThan(0);
    expect(screen.getAllByText("分镜返工").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "打开 E1" })).toBeInTheDocument();
  });

  it("exports the production board as a CSV checklist", async () => {
    const createObjectURL = vi.fn((_blob: Blob) => "blob:production-board");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    vi.spyOn(API, "getScriptReview").mockResolvedValue(productionReviewState());

    render(
      <OverviewCanvas
        projectName="demo"
        projectData={makeProjectData({
          content_mode: "drama",
          episodes: [{ episode: 1, title: "雨夜真相", script_file: "scripts/episode_1.json" }],
        })}
      />,
    );

    fireEvent.click(await screen.findByText("导出生产清单"));

    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
    const blob = createObjectURL.mock.calls[0][0] as Blob;
    await expect(blob.text()).resolves.toContain("episode,title,script,storyboard,video,export,issues");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:production-board");
  });
});

describe("OverviewCanvas ad mode", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    useProjectsStore.setState(useProjectsStore.getInitialState(), true);
    vi.restoreAllMocks();
  });

  it("hides episode semantics for ad projects", () => {
    render(
      <OverviewCanvas
        projectName="ad-demo"
        projectData={makeProjectData({
          content_mode: "ad",
          target_duration: 60,
          brief: "卖点",
          episodes: [{ episode: 1, title: "", script_file: "scripts/episode_1.json" }],
        })}
      />,
    );
    // 不出现「集」概念：无 E1 徽标、无「剧集」标题
    expect(screen.queryByText("E1")).not.toBeInTheDocument();
    expect(screen.queryByText("剧集")).not.toBeInTheDocument();
    // 改为「视频」区块标题
    expect(screen.getByText("视频")).toBeInTheDocument();
  });

  it("keeps episode semantics for narration projects", () => {
    render(<OverviewCanvas projectName="demo" projectData={makeProjectData()} />);
    expect(screen.getAllByText("E1").length).toBeGreaterThan(0);
  });

  it("shows ad init canvas when ad project has no products and no brief", () => {
    render(
      <OverviewCanvas
        projectName="ad-demo"
        projectData={makeProjectData({
          content_mode: "ad",
          overview: undefined,
          target_duration: 60,
          brief: "",
          products: {},
          episodes: [{ episode: 1, title: "", script_file: "scripts/episode_1.json" }],
        })}
      />,
    );
    expect(screen.getByTestId("ad-init-canvas")).toBeInTheDocument();
  });

  it("skips ad init canvas once brief or products exist", () => {
    render(
      <OverviewCanvas
        projectName="ad-demo"
        projectData={makeProjectData({
          content_mode: "ad",
          target_duration: 60,
          brief: "卖点",
          episodes: [{ episode: 1, title: "", script_file: "scripts/episode_1.json" }],
        })}
      />,
    );
    expect(screen.queryByTestId("ad-init-canvas")).not.toBeInTheDocument();
  });

  it("never shows ad init canvas for narration projects", () => {
    render(
      <OverviewCanvas
        projectName="demo"
        projectData={makeProjectData({ overview: undefined, episodes: [] })}
      />,
    );
    expect(screen.queryByTestId("ad-init-canvas")).not.toBeInTheDocument();
    expect(screen.getByTestId("welcome-canvas")).toBeInTheDocument();
  });
});
