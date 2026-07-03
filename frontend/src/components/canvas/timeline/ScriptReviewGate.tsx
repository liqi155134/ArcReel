import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, CheckCircle2, Clock, Lock, RotateCcw, Save } from "lucide-react";
import { API } from "@/api";
import type {
  DramaNormalizedScript,
  DramaSceneContent,
  NarrationStep1Draft,
  NarrationStep1Segment,
  ScriptReviewState,
  Utterance,
  LocalWorkflowGate,
  LocalWorkflowDecision,
  LocalWorkflowChecklist,
  LocalWorkflowReviewUpdate,
} from "@/types";
import { useAppStore } from "@/stores/app-store";
import { voidPromise } from "@/utils/async";
import { AutoTextarea } from "@/components/ui/AutoTextarea";
import {
  ACCENT_BUTTON_STYLE,
  ACCENT_BTN_CLS,
  CARD_STYLE,
  GHOST_BTN_CLS,
  GHOST_BTN_LG_CLS,
} from "@/components/ui/darkroom-tokens";
import { UtteranceListEditor } from "./UtteranceListEditor";
import { deriveLocalWorkflowStages, type LocalWorkflowStageStatus } from "./localWorkflow";

interface ScriptReviewGateProps {
  projectName: string;
  episode: number;
  contentMode: "narration" | "drama";
}

const SECTION_LABEL_STYLE: React.CSSProperties = {
  color: "var(--color-text-4)",
  letterSpacing: "0.08em",
  fontFamily: "var(--font-mono)",
};

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "";
}

/** Read-only 资产引用 pills（出场角色 / 场景 / 道具），由 step1 登记、gate 不改。 */
function MetaChips({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((name) => (
        <span
          key={name}
          className="rounded border border-hairline bg-bg-grad-a/50 px-1.5 py-0.5 text-[10.5px] text-text-3"
        >
          {name}
        </span>
      ))}
    </div>
  );
}

function SceneHeader({
  id,
  durationSeconds,
  segmentBreak,
}: {
  id: string;
  durationSeconds: number;
  segmentBreak: boolean;
}) {
  const { t } = useTranslation("dashboard");
  return (
    <div className="flex items-center gap-2">
      <span className="rounded bg-bg-grad-a/70 px-1.5 py-0.5 font-mono text-[11px] text-text-2">{id}</span>
      <span className="text-[11px] text-text-4">{durationSeconds}s</span>
      {segmentBreak && (
        <span className="rounded border border-hairline px-1.5 py-0.5 text-[10px] text-text-4">
          {t("review_segment_break")}
        </span>
      )}
    </div>
  );
}

function DramaSceneCard({
  scene,
  disabled,
  onChange,
}: {
  scene: DramaSceneContent;
  disabled: boolean;
  onChange: (patch: Partial<DramaSceneContent>) => void;
}) {
  const { t } = useTranslation("dashboard");
  return (
    <article className="rounded-[10px] border border-hairline p-3.5" style={CARD_STYLE}>
      <div className="mb-3 flex items-start justify-between gap-2">
        <SceneHeader id={scene.scene_id} durationSeconds={scene.duration_seconds} segmentBreak={scene.segment_break} />
        <MetaChips items={scene.characters_in_scene} />
      </div>

      <label className="mb-1 block text-[10.5px]" style={SECTION_LABEL_STYLE}>
        {t("review_utterances_label")}
      </label>
      <UtteranceListEditor
        utterances={scene.utterances}
        disabled={disabled}
        onChange={(utterances: Utterance[]) => onChange({ utterances })}
      />

      <label className="mb-1 mt-3 block text-[10.5px]" style={SECTION_LABEL_STYLE}>
        {t("review_source_text_label")}
      </label>
      <AutoTextarea
        value={scene.source_text}
        disabled={disabled}
        onChange={(source_text) => onChange({ source_text })}
        placeholder={t("review_source_text_placeholder")}
        aria-label={t("review_source_text_label")}
        className="text-text-3"
      />
    </article>
  );
}


const WORKFLOW_STAGE_IDS = [
  "brief_gate",
  "script_gate",
  "asset_gate",
  "storyboard_gate",
  "video_gate",
  "export_gate",
] as const;

const WORKFLOW_STATUS_CLASS: Record<LocalWorkflowStageStatus, string> = {
  complete: "border-emerald-400/25 bg-emerald-950/15 text-emerald-200",
  ready: "border-sky-400/25 bg-sky-950/15 text-sky-200",
  warning: "border-amber-400/25 bg-amber-950/15 text-amber-200",
  blocked: "border-rose-400/35 bg-rose-950/20 text-rose-200",
  locked: "border-hairline bg-bg/35 text-text-4",
};

const WORKFLOW_REVIEW_BADGE_COMPLETE_CLS =
  "rounded border border-emerald-400/25 bg-emerald-950/15 px-2 py-1 text-[11.5px] text-emerald-200";
const WORKFLOW_REVIEW_BADGE_WARNING_CLS =
  "rounded border border-amber-400/30 bg-amber-950/15 px-2 py-1 text-[11.5px] text-amber-200";

const WORKFLOW_CHECKLIST_ITEMS: Record<LocalWorkflowGate, readonly string[]> = {
  storyboard: ["character_consistency", "scene_prop_consistency", "shot_count", "prompt_quality"],
  video: ["motion_continuity", "face_stability", "duration_rhythm", "first_last_frame"],
  export: ["subtitles_audio", "aspect_cover", "file_naming", "final_playback"],
};

const WORKFLOW_REVIEW_GATES = ["storyboard", "video", "export"] as const;

function LocalWorkflowOverview({
  state,
  busy,
  onSetWorkflowGate,
}: {
  state: ScriptReviewState;
  busy: boolean;
  onSetWorkflowGate: (gate: LocalWorkflowGate, reviewed: boolean, review?: LocalWorkflowReviewUpdate) => void;
}) {
  const { t } = useTranslation("dashboard");
  const workflow = state.local_workflow_reviews;
  const [reviewNotes, setReviewNotes] = useState<Record<LocalWorkflowGate, string>>({
    storyboard: workflow.storyboard_note,
    video: workflow.video_note,
    export: workflow.export_note,
  });
  const [reviewChecklists, setReviewChecklists] = useState<Record<LocalWorkflowGate, LocalWorkflowChecklist>>({
    storyboard: workflow.storyboard_checklist,
    video: workflow.video_checklist,
    export: workflow.export_checklist,
  });
  const stages = deriveLocalWorkflowStages({
    reviewStatus: state.status,
    qaGateStatus: state.qa_gate_status,
    storyboardReviewed: workflow.storyboard_reviewed,
    storyboardDecision: workflow.storyboard_decision,
    videoReviewed: workflow.video_reviewed,
    videoDecision: workflow.video_decision,
    exportReviewed: workflow.export_reviewed,
    exportDecision: workflow.export_decision,
  });
  const canMarkStoryboardReviewed = state.status === "confirmed" && !workflow.storyboard_reviewed;
  const canMarkVideoReviewed = state.status === "confirmed" && workflow.storyboard_reviewed && !workflow.video_reviewed;
  const canMarkExportReviewed = state.status === "confirmed" && workflow.video_reviewed && !workflow.export_reviewed;
  const labelById = Object.fromEntries(
    WORKFLOW_STAGE_IDS.map((id) => [id, t(`local_workflow_stage_${id}`)]),
  ) as Record<(typeof WORKFLOW_STAGE_IDS)[number], string>;
  const gateReviews: Record<
    LocalWorkflowGate,
    {
      decision: LocalWorkflowDecision;
      note: string;
      checklist: LocalWorkflowChecklist;
      label: string;
    }
  > = {
    storyboard: {
      decision: workflow.storyboard_decision,
      note: workflow.storyboard_note,
      checklist: workflow.storyboard_checklist,
      label: t("local_workflow_stage_storyboard_gate"),
    },
    video: {
      decision: workflow.video_decision,
      note: workflow.video_note,
      checklist: workflow.video_checklist,
      label: t("local_workflow_stage_video_gate"),
    },
    export: {
      decision: workflow.export_decision,
      note: workflow.export_note,
      checklist: workflow.export_checklist,
      label: t("local_workflow_stage_export_gate"),
    },
  };
  const reworkGate = WORKFLOW_REVIEW_GATES.find((gate) => gateReviews[gate].decision === "needs_changes");
  const rework = reworkGate ? { gate: reworkGate, ...gateReviews[reworkGate] } : null;
  const failedChecklistLabels = rework
    ? WORKFLOW_CHECKLIST_ITEMS[rework.gate]
        .filter((item) => rework.checklist[item] !== true)
        .map((item) => t(`local_workflow_checklist_${item}`))
    : [];
  const markReworkFixed = () => {
    if (!rework) return;
    onSetWorkflowGate(rework.gate, false, {
      decision: "pending",
      note: "",
      checklist: rework.checklist,
    });
  };
  const renderReviewControls = (
    gate: LocalWorkflowGate,
    canReview: boolean,
    noteLabelKey: string,
    approveLabelKey: string,
  ) => {
    const submitReview = (reviewed: boolean, decision: LocalWorkflowDecision) =>
      onSetWorkflowGate(gate, reviewed, {
        decision,
        note: reviewNotes[gate],
        checklist: reviewChecklists[gate],
      });

    if (!canReview) return null;
    return (
      <div className="grid w-full gap-2">
        <div className="rounded-[8px] border border-hairline bg-bg/30 px-2.5 py-2">
          <div className="mb-1 text-[11px] font-medium text-text-3">{t("local_workflow_checklist_title")}</div>
          <div className="grid gap-1.5 md:grid-cols-2 xl:grid-cols-4">
            {WORKFLOW_CHECKLIST_ITEMS[gate].map((item) => (
              <label key={item} className="flex items-center gap-1.5 text-[11.5px] text-text-3">
                <input
                  type="checkbox"
                  checked={reviewChecklists[gate][item] === true}
                  onChange={(event) =>
                    setReviewChecklists((prev) => ({
                      ...prev,
                      [gate]: {
                        ...prev[gate],
                        [item]: event.target.checked,
                      },
                    }))
                  }
                  className="h-3.5 w-3.5 accent-accent"
                />
                {t(`local_workflow_checklist_${item}`)}
              </label>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            aria-label={t(noteLabelKey)}
            value={reviewNotes[gate]}
            onChange={(event) => setReviewNotes((prev) => ({ ...prev, [gate]: event.target.value }))}
            placeholder={t("local_workflow_review_note_placeholder")}
            className="min-w-64 flex-1 rounded border border-hairline bg-bg/50 px-2 py-1 text-[12px] text-text-2 outline-none focus:border-accent"
          />
          <button
            type="button"
            className={GHOST_BTN_CLS}
            disabled={busy}
            onClick={() => submitReview(false, "needs_changes")}
          >
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
            {t("local_workflow_needs_changes")}
          </button>
          <button
            type="button"
            className={GHOST_BTN_CLS}
            disabled={busy}
            onClick={() => submitReview(true, "approved")}
          >
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
            {t(approveLabelKey)}
          </button>
        </div>
      </div>
    );
  };
  const renderReviewBadge = (
    reviewed: boolean,
    decision: LocalWorkflowDecision,
    note: string,
    reviewedLabelKey: string,
  ) => {
    if (!reviewed && decision !== "needs_changes" && !note) return null;
    return (
      <span className={reviewed ? WORKFLOW_REVIEW_BADGE_COMPLETE_CLS : WORKFLOW_REVIEW_BADGE_WARNING_CLS}>
        {reviewed ? t(reviewedLabelKey) : t("local_workflow_needs_changes")}
        {note ? ` · ${note}` : ""}
      </span>
    );
  };

  return (
    <section className="rounded-[10px] border border-hairline px-3.5 py-3" style={CARD_STYLE} aria-label={t("local_workflow_title")}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-[12.5px] font-medium text-text">{t("local_workflow_title")}</h3>
          <p className="mt-0.5 text-[11px] text-text-4">{t("local_workflow_hint")}</p>
        </div>
      </div>
      <ol className="grid gap-2 md:grid-cols-3 xl:grid-cols-6">
        {stages.map((stage, index) => {
          const label = labelById[stage.id];
          const statusLabel = t(`local_workflow_status_${stage.status}`);
          return (
            <li
              key={stage.id}
              aria-label={`${label}：${statusLabel}`}
              className={`rounded-[9px] border px-2.5 py-2 ${WORKFLOW_STATUS_CLASS[stage.status]}`}
            >
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="font-mono text-[10px] text-text-5">{String(index + 1).padStart(2, "0")}</span>
                <span className="rounded bg-bg/40 px-1.5 py-0.5 font-mono text-[9.5px] uppercase">{statusLabel}</span>
              </div>
              <div className="text-[12px] font-medium">{label}</div>
            </li>
          );
        })}
      </ol>
      {rework ? (
        <div className="mt-2 rounded-[8px] border border-amber-400/30 bg-amber-950/15 px-2.5 py-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-[12px] font-medium text-amber-100">
                {t("local_workflow_current_blocker", { stage: rework.label })}
              </div>
              <div className="mt-0.5 text-[11.5px] text-amber-100/80">
                {rework.note || t("local_workflow_rework_no_note")}
              </div>
              {failedChecklistLabels.length > 0 ? (
                <div className="mt-0.5 text-[11.5px] text-amber-100/80">
                  {t("local_workflow_failed_checklist", { items: failedChecklistLabels.join("、") })}
                </div>
              ) : null}
            </div>
            <button type="button" className={GHOST_BTN_CLS} disabled={busy} onClick={markReworkFixed}>
              <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
              {t("local_workflow_mark_fixed")}
            </button>
          </div>
          <div className="mt-1 text-[11px] text-amber-100/70">{t("local_workflow_rework_hint")}</div>
        </div>
      ) : null}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {renderReviewControls(
          "storyboard",
          canMarkStoryboardReviewed,
          "local_workflow_storyboard_note_label",
          "local_workflow_mark_storyboard_reviewed",
        )}
        {renderReviewBadge(
          workflow.storyboard_reviewed,
          workflow.storyboard_decision,
          workflow.storyboard_note,
          "local_workflow_storyboard_reviewed",
        )}
        {renderReviewControls(
          "video",
          canMarkVideoReviewed,
          "local_workflow_video_note_label",
          "local_workflow_mark_video_reviewed",
        )}
        {renderReviewBadge(
          workflow.video_reviewed,
          workflow.video_decision,
          workflow.video_note,
          "local_workflow_video_reviewed",
        )}
        {renderReviewControls(
          "export",
          canMarkExportReviewed,
          "local_workflow_export_note_label",
          "local_workflow_mark_export_reviewed",
        )}
        {renderReviewBadge(
          workflow.export_reviewed,
          workflow.export_decision,
          workflow.export_note,
          "local_workflow_export_reviewed",
        )}
      </div>
    </section>
  );
}

function QaFindingsPanel({ state }: { state: ScriptReviewState }) {
  const { t } = useTranslation("dashboard");
  const findings = state.qa_findings ?? [];
  const summary = state.qa_summary;
  if (!summary || findings.length === 0) return null;

  const blocked = state.qa_gate_status === "blocked";
  const panelClassName = blocked
    ? "rounded-[10px] border border-rose-400/35 bg-rose-950/20 px-3.5 py-3"
    : "rounded-[10px] border border-amber-400/25 bg-amber-950/15 px-3.5 py-3";
  const iconClassName = blocked ? "h-4 w-4 text-rose-300" : "h-4 w-4 text-amber-300";
  return (
    <section className={panelClassName} aria-label={t("review_qa_title")}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <AlertTriangle className={iconClassName} aria-hidden="true" />
          <span className="text-[12.5px] font-medium text-text">{t("review_qa_title")}</span>
        </div>
        <span className="font-mono text-[11px] text-text-4">
          {t("review_qa_summary", {
            block: summary.block_count,
            warn: summary.warn_count,
            info: summary.info_count,
          })}
        </span>
      </div>
      {blocked && <p className="mb-2 text-[11.5px] text-rose-200">{t("review_qa_blocked_hint")}</p>}
      <ul className="flex flex-col gap-2">
        {findings.map((finding, index) => (
          <li key={`${finding.code}-${finding.path ?? index}`} className="rounded border border-hairline bg-bg/40 p-2">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`rounded px-1.5 py-0.5 font-mono text-[10px] uppercase ${
                  finding.severity === "block"
                    ? "bg-rose-500/20 text-rose-200"
                    : finding.severity === "warn"
                      ? "bg-amber-500/20 text-amber-200"
                      : "bg-sky-500/20 text-sky-200"
                }`}
              >
                {finding.severity}
              </span>
              <span className="font-mono text-[10.5px] text-text-4">{finding.code}</span>
              {finding.path && <span className="font-mono text-[10.5px] text-text-5">{finding.path}</span>}
            </div>
            <p className="mt-1 text-[12px] text-text-2">{finding.message}</p>
            {finding.evidence && <p className="mt-1 font-mono text-[10.5px] text-text-4">{finding.evidence}</p>}
            {finding.recommendation && (
              <p className="mt-1 text-[11.5px] text-text-3">
                {t("review_qa_recommendation")}: {finding.recommendation}
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function NarrationSegmentCard({
  segment,
  disabled,
  onChange,
}: {
  segment: NarrationStep1Segment;
  disabled: boolean;
  onChange: (patch: Partial<NarrationStep1Segment>) => void;
}) {
  const { t } = useTranslation("dashboard");
  return (
    <article className="rounded-[10px] border border-hairline p-3.5" style={CARD_STYLE}>
      <div className="mb-3 flex items-start justify-between gap-2">
        <SceneHeader
          id={segment.segment_id}
          durationSeconds={segment.duration_seconds}
          segmentBreak={segment.segment_break}
        />
        <MetaChips items={segment.characters_in_segment} />
      </div>

      <label className="mb-1 block text-[10.5px]" style={SECTION_LABEL_STYLE}>
        {t("review_novel_text_label")}
      </label>
      <AutoTextarea
        value={segment.novel_text}
        onChange={(novel_text) => onChange({ novel_text })}
        placeholder={t("review_novel_text_placeholder")}
        aria-label={t("review_novel_text_label")}
        disabled={disabled}
      />
    </article>
  );
}

/** 内容是否有未保存编辑：以序列化比对，draft 由 server content 克隆而来，键序稳定。 */
function isDirty(draft: unknown, serverContent: unknown): boolean {
  if (draft == null) return false;
  return JSON.stringify(draft) !== JSON.stringify(serverContent);
}

/**
 * step1→step2 web 审核 gate 面板：把 step1 结构化中间态在网页结构化呈现、可手动 / agent 编辑，
 * 用户显式确认后才放行 step2 视觉生成。drama（utterances + source_text）与 narration
 * （novel_text）共用本面板。
 */
export function ScriptReviewGate({ projectName, episode, contentMode }: ScriptReviewGateProps) {
  const { t } = useTranslation("dashboard");
  const pushToast = useAppStore((s) => s.pushToast);
  const draftRevision = useAppStore((s) => s.getEntityRevision(`draft:episode_${episode}_step1`));

  const [state, setState] = useState<ScriptReviewState | null>(null);
  const [draft, setDraft] = useState<DramaNormalizedScript | NarrationStep1Draft | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<{ message: string } | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [workflowSaving, setWorkflowSaving] = useState(false);

  const serverContent = state?.content ?? null;
  const dirty = useMemo(() => isDirty(draft, serverContent), [draft, serverContent]);
  const busy = saving || confirming || workflowSaving;

  // 把 dirty 镜像进 ref，供下方拉取 effect 读取最新值，而无需把 dirty 列入 deps（否则每次编辑都会重新拉取）。
  const dirtyRef = useRef(false);
  useEffect(() => {
    dirtyRef.current = dirty;
  }, [dirty]);

  // 采用服务端内容为新草稿（深克隆，避免与服务端态共享引用）。用户主动动作（保存 / 确认）后调用，
  // 总是覆盖本地草稿；setDraft 传值而非更新器，保持纯净、不在更新器内读写 ref。
  const adopt = useCallback((next: ScriptReviewState) => {
    setState(next);
    setDraft(
      next.content ? (JSON.parse(JSON.stringify(next.content)) as DramaNormalizedScript | NarrationStep1Draft) : null,
    );
  }, []);

  const handleRetry = useCallback(() => {
    setLoadError(null);
    setLoading(true);
    setReloadNonce((n) => n + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    // 已拿到过任一响应（空态或内容态）后，revision 触发的重新拉取静默刷新、不闪加载态；
    const hadResponse = state != null;
    // 屏上有真实内容可保留时，刷新失败静默保留、不破坏用户视图；无内容（首屏，或空态）时失败才进错误态。
    const hasContent = draft != null;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!hadResponse) setLoading(true);
    API.getScriptReview(projectName, episode)
      .then((next) => {
        if (cancelled) return;
        setLoadError(null);
        setState(next);
        // 外部刷新（挂载 / agent 改 step1 触发的 revision）：用户无未保存编辑时采用服务端内容，
        // 有编辑则仅更新服务端态、保留用户草稿。dirtyRef 读取在 effect 内安全（非 render 期）。
        if (!dirtyRef.current) {
          setDraft(
            next.content
              ? (JSON.parse(JSON.stringify(next.content)) as DramaNormalizedScript | NarrationStep1Draft)
              : null,
          );
        }
      })
      .catch((err) => {
        if (cancelled) return;
        // 屏上无真实内容（首屏失败，或空态后 revision 刷新失败）→ 错误态（区别于空态）+ 重试；
        // 已有内容的静默刷新失败则保留现有内容，不破坏用户视图。
        if (!hasContent) setLoadError({ message: errorMessage(err) });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- state/draft 仅用于决定加载态与错误态分支，加入 deps 会在每次刷新后重新拉取造成循环
  }, [projectName, episode, draftRevision, reloadNonce]);

  const handleSave = useCallback(async () => {
    if (!draft) return;
    setSaving(true);
    try {
      adopt(await API.saveScriptReviewContent(projectName, episode, draft));
      pushToast(t("dashboard:review_saved"), "success");
    } catch (err) {
      pushToast(errorMessage(err) || t("dashboard:save_failed", { message: "" }), "error");
    } finally {
      setSaving(false);
    }
  }, [draft, projectName, episode, adopt, pushToast, t]);

  const handleConfirm = useCallback(async () => {
    setConfirming(true);
    try {
      if (dirty && draft) {
        adopt(await API.saveScriptReviewContent(projectName, episode, draft));
      }
      adopt(await API.confirmScriptReview(projectName, episode));
      pushToast(t("dashboard:review_confirmed"), "success");
    } catch (err) {
      pushToast(errorMessage(err) || t("dashboard:review_confirm_failed"), "error");
    } finally {
      setConfirming(false);
    }
  }, [dirty, draft, projectName, episode, adopt, pushToast, t]);



  const handleSetWorkflowGate = useCallback(
    async (gate: LocalWorkflowGate, reviewed: boolean, review?: LocalWorkflowReviewUpdate) => {
      setWorkflowSaving(true);
      try {
        adopt(await API.setScriptReviewWorkflowGate(projectName, episode, gate, reviewed, review));
        pushToast(t("dashboard:local_workflow_review_saved"), "success");
      } catch (err) {
        pushToast(errorMessage(err) || t("dashboard:save_failed", { message: "" }), "error");
      } finally {
        setWorkflowSaving(false);
      }
    },
    [projectName, episode, adopt, pushToast, t],
  );

  const updateDramaScene = (index: number, patch: Partial<DramaSceneContent>) => {
    setDraft((prev) => {
      if (!prev || !("scenes" in prev)) return prev;
      return { ...prev, scenes: prev.scenes.map((s, i) => (i === index ? { ...s, ...patch } : s)) };
    });
  };

  const updateNarrationSegment = (index: number, patch: Partial<NarrationStep1Segment>) => {
    setDraft((prev) => {
      if (!prev || !("segments" in prev)) return prev;
      return { ...prev, segments: prev.segments.map((s, i) => (i === index ? { ...s, ...patch } : s)) };
    });
  };

  if (loading) {
    return <div className="flex h-64 items-center justify-center text-text-4">{t("dashboard:loading_preprocessing")}</div>;
  }

  // 加载错误态：区别于「无 step1 产物」空态，展示错误信息 + 重试入口。
  if (loadError) {
    return (
      <div role="alert" className="flex h-64 flex-col items-center justify-center gap-3 text-center">
        <AlertTriangle className="h-6 w-6 text-amber-400" aria-hidden="true" />
        <div className="flex flex-col gap-1">
          <p className="text-[13px] font-medium text-text-2">{t("dashboard:review_load_failed")}</p>
          {loadError.message && (
            <p className="max-w-sm px-4 font-mono text-[11px] text-text-4">{loadError.message}</p>
          )}
        </div>
        <button type="button" onClick={handleRetry} className={GHOST_BTN_LG_CLS}>
          <RotateCcw className="h-3.5 w-3.5" />
          {t("dashboard:review_retry")}
        </button>
      </div>
    );
  }

  const status = state?.status ?? "no_step1";
  if (status === "no_step1" || draft == null) {
    return (
      <div className="flex h-64 items-center justify-center text-text-4">{t("dashboard:no_preprocessing_content")}</div>
    );
  }

  const confirmed = status === "confirmed" && !dirty;
  const qaBlocked = state?.qa_gate_status === "blocked";

  return (
    <div className="flex flex-col gap-3">
      {/* 审核状态条 + 确认动作 */}
      <header
        className="sticky top-0 z-10 flex items-center justify-between gap-3 rounded-[10px] border border-hairline px-3.5 py-2.5 backdrop-blur-md"
        style={CARD_STYLE}
      >
        <div className="flex items-center gap-2">
          {confirmed ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-400" />
          ) : (
            <Clock className="h-4 w-4 text-amber-400" />
          )}
          <div className="flex flex-col">
            <span className="text-[12.5px] font-medium text-text">
              {confirmed ? t("dashboard:review_status_confirmed") : t("dashboard:review_status_pending")}
            </span>
            <span className="text-[11px] text-text-4">
              {confirmed ? t("dashboard:review_confirmed_hint") : t("dashboard:review_pending_hint")}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {dirty && (
            <button type="button" onClick={voidPromise(handleSave)} disabled={busy} className={GHOST_BTN_CLS}>
              <Save className="h-3.5 w-3.5" />
              {saving ? t("common:saving") : t("common:save")}
            </button>
          )}
          <button
            type="button"
            onClick={voidPromise(handleConfirm)}
            disabled={busy || confirmed || qaBlocked}
            title={qaBlocked ? t("dashboard:review_qa_blocked_hint") : undefined}
            className={ACCENT_BTN_CLS}
            style={ACCENT_BUTTON_STYLE}
          >
            {confirmed ? <Lock className="h-3.5 w-3.5" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
            {confirming
              ? t("dashboard:review_confirming")
              : confirmed
                ? t("dashboard:review_confirmed_badge")
                : t("dashboard:review_confirm_action")}
          </button>
        </div>
      </header>

      {state ? <LocalWorkflowOverview state={state} busy={busy} onSetWorkflowGate={voidPromise(handleSetWorkflowGate)} /> : null}

      {state ? <QaFindingsPanel state={state} /> : null}

      {/* 结构化中间态卡片 */}
      <div className="flex flex-col gap-2.5">
        {contentMode === "drama" && "scenes" in draft
          ? draft.scenes.map((scene, i) => (
              <DramaSceneCard
                key={scene.scene_id || i}
                scene={scene}
                disabled={busy}
                onChange={(patch) => updateDramaScene(i, patch)}
              />
            ))
          : null}
        {contentMode === "narration" && "segments" in draft
          ? draft.segments.map((segment, i) => (
              <NarrationSegmentCard
                key={segment.segment_id || i}
                segment={segment}
                disabled={busy}
                onChange={(patch) => updateNarrationSegment(i, patch)}
              />
            ))
          : null}
      </div>
    </div>
  );
}
