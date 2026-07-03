import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "wouter";
import { API } from "@/api";
import type { EpisodeMeta, ScriptReviewState } from "@/types";
import {
  buildEpisodeProductionCsv,
  deriveEpisodeProductionRows,
  PRODUCTION_ISSUE_LABELS,
  PRODUCTION_STAGE_LABELS,
  summarizeEpisodeProductionRows,
  type EpisodeProductionRow,
  type ProductionIssueCode,
  type ProductionStageStatus,
} from "./productionBoard";

const CARD_BG =
  "linear-gradient(180deg, oklch(0.22 0.012 265 / 0.55), oklch(0.19 0.010 265 / 0.40))";
const CARD_SHADOW =
  "inset 0 1px 0 oklch(1 0 0 / 0.04), 0 8px 24px -10px oklch(0 0 0 / 0.5)";

const STAGE_CLASS: Record<ProductionStageStatus, string> = {
  not_started: "border-hairline bg-bg/30 text-text-4",
  pending: "border-sky-400/25 bg-sky-950/15 text-sky-200",
  blocked: "border-rose-400/35 bg-rose-950/20 text-rose-200",
  needs_changes: "border-amber-400/30 bg-amber-950/15 text-amber-200",
  approved: "border-emerald-400/25 bg-emerald-950/15 text-emerald-200",
  missing_artifact: "border-fuchsia-400/30 bg-fuchsia-950/15 text-fuchsia-200",
  locked: "border-hairline bg-bg/20 text-text-5",
};

const ISSUE_CLASS: Record<ProductionIssueCode, string> = {
  qa_blocked: "border-rose-400/35 bg-rose-950/20 text-rose-200",
  storyboard_rework: "border-amber-400/30 bg-amber-950/15 text-amber-200",
  video_rework: "border-amber-400/30 bg-amber-950/15 text-amber-200",
  export_rework: "border-amber-400/30 bg-amber-950/15 text-amber-200",
  missing_prompt: "border-sky-400/25 bg-sky-950/15 text-sky-200",
  missing_storyboard_artifact: "border-fuchsia-400/30 bg-fuchsia-950/15 text-fuchsia-200",
  missing_video_artifact: "border-fuchsia-400/30 bg-fuchsia-950/15 text-fuchsia-200",
  missing_export_artifact: "border-fuchsia-400/30 bg-fuchsia-950/15 text-fuchsia-200",
  review_unavailable: "border-hairline bg-bg/30 text-text-4",
};

interface EpisodeProductionBoardProps {
  projectName: string;
  episodes: EpisodeMeta[];
}

function StageBadge({ status }: { status: ProductionStageStatus }) {
  return (
    <span className={`inline-flex rounded border px-1.5 py-0.5 text-[10.5px] ${STAGE_CLASS[status]}`}>
      {PRODUCTION_STAGE_LABELS[status]}
    </span>
  );
}

function IssueChip({ issue }: { issue: ProductionIssueCode }) {
  return (
    <span className={`inline-flex rounded border px-1.5 py-0.5 text-[10.5px] ${ISSUE_CLASS[issue]}`}>
      {PRODUCTION_ISSUE_LABELS[issue]}
    </span>
  );
}

function SummaryCard({ label, value }: { label: string; value: number }) {
  return (
    <div
      className="rounded-xl px-3 py-2"
      style={{
        border: "1px solid var(--color-hairline-soft)",
        background: "oklch(0.18 0.010 265 / 0.35)",
      }}
    >
      <div className="text-[10.5px] text-text-4">{label}</div>
      <div className="num mt-0.5 text-[18px] font-semibold text-text">{value}</div>
    </div>
  );
}

function exportRows(projectName: string, rows: readonly EpisodeProductionRow[]) {
  const csv = buildEpisodeProductionCsv(rows);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${projectName}-episode-production-board.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function EpisodeProductionBoard({ projectName, episodes }: EpisodeProductionBoardProps) {
  const { t } = useTranslation("dashboard");
  const [, setLocation] = useLocation();
  const [states, setStates] = useState<Partial<Record<number, ScriptReviewState | null>>>({});
  const episodeNumbers = useMemo(() => episodes.map((episode) => episode.episode), [episodes]);

  useEffect(() => {
    let cancelled = false;
    void Promise.allSettled(episodeNumbers.map((episode) => API.getScriptReview(projectName, episode))).then((results) => {
      if (cancelled) return;
      const next: Partial<Record<number, ScriptReviewState | null>> = {};
      results.forEach((result, index) => {
        next[episodeNumbers[index]] = result.status === "fulfilled" ? result.value : null;
      });
      setStates(next);
    });
    return () => {
      cancelled = true;
    };
  }, [projectName, episodeNumbers]);

  const rows = useMemo(() => deriveEpisodeProductionRows(episodes, states), [episodes, states]);
  const summary = useMemo(() => summarizeEpisodeProductionRows(rows), [rows]);

  if (episodes.length === 0) return null;

  return (
    <section
      className="relative overflow-hidden rounded-2xl p-5"
      style={{
        border: "1px solid var(--color-hairline-soft)",
        background: CARD_BG,
        boxShadow: CARD_SHADOW,
      }}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2.5">
        <div>
          <h3 className="display-serif text-[15px] font-semibold tracking-tight text-text">
            {t("production_board_title")}
          </h3>
          <p className="mt-0.5 text-[11px] text-text-4">{t("production_board_hint")}</p>
        </div>
        <div className="flex-1" />
        <button
          type="button"
          onClick={() => exportRows(projectName, rows)}
          className="focus-ring inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11.5px] text-text-3 transition-colors hover:bg-[oklch(1_0_0_/_0.05)] hover:text-text"
        >
          {t("production_board_export_csv")}
        </button>
      </div>

      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-5">
        <SummaryCard label={t("production_board_qa_blocked")} value={summary.qaBlocked} />
        <SummaryCard label={t("production_board_rework")} value={summary.rework} />
        <SummaryCard label={t("production_board_missing_prompt")} value={summary.missingPrompt} />
        <SummaryCard label={t("production_board_missing_video")} value={summary.missingVideo} />
        <SummaryCard label={t("production_board_missing_export")} value={summary.missingExport} />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[780px] border-separate border-spacing-y-1 text-left text-[12px]">
          <thead className="text-[10.5px] uppercase text-text-4">
            <tr>
              <th className="px-2 py-1">{t("production_board_episode")}</th>
              <th className="px-2 py-1">{t("production_board_script")}</th>
              <th className="px-2 py-1">{t("production_board_storyboard")}</th>
              <th className="px-2 py-1">{t("production_board_video")}</th>
              <th className="px-2 py-1">{t("production_board_export")}</th>
              <th className="px-2 py-1">{t("production_board_issues")}</th>
              <th className="px-2 py-1" aria-label={t("production_board_actions")} />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.episode} className="rounded-xl bg-bg/25 text-text-2">
                <td className="rounded-l-xl px-2 py-2">
                  <div className="flex items-center gap-2">
                    <span className="rounded border border-accent-soft bg-accent-dim px-1.5 py-0.5 text-[10.5px] font-bold text-accent-2">
                      E{row.episode}
                    </span>
                    <span className="font-medium text-text">{row.title}</span>
                  </div>
                </td>
                <td className="px-2 py-2"><StageBadge status={row.script} /></td>
                <td className="px-2 py-2"><StageBadge status={row.storyboard} /></td>
                <td className="px-2 py-2"><StageBadge status={row.video} /></td>
                <td className="px-2 py-2"><StageBadge status={row.export} /></td>
                <td className="px-2 py-2">
                  <div className="flex flex-wrap gap-1">
                    {row.issues.length > 0 ? row.issues.map((issue) => <IssueChip key={issue} issue={issue} />) : <span className="text-text-4">-</span>}
                  </div>
                </td>
                <td className="rounded-r-xl px-2 py-2 text-right">
                  <button
                    type="button"
                    onClick={() => setLocation(`/episodes/${row.episode}`)}
                    className="focus-ring inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-text-3 hover:bg-[oklch(1_0_0_/_0.05)] hover:text-text"
                  >
                    {t("production_board_open_episode", { episode: row.episode })}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
