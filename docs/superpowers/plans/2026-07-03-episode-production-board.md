# Episode Production Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a project-level short-drama production board that aggregates per-episode manual review, QA, prompt, and artifact status for local human production.

**Architecture:** Keep the board read-only and manual-first. The overview page fetches existing per-episode script-review states, derives compact row/status/issue summaries in a pure helper, renders a lightweight table with quick episode jump buttons, and exports a CSV production checklist through browser APIs. No provider integration, no auto-generation, no unattended batch actions.

**Tech Stack:** React/Vitest, existing `OverviewCanvas`, existing `API.getScriptReview`, TypeScript helper functions, browser Blob/URL APIs.

---

### Task 1: Pure production-board derivation

**Files:**
- Create: `frontend/src/components/canvas/productionBoard.ts`
- Test: `frontend/src/components/canvas/productionBoard.test.ts`

- [x] **Step 1: Write failing helper tests**

Add tests that create three episode states and assert:
1. A QA-blocked episode reports script `blocked` and a QA issue.
2. A storyboard `needs_changes` episode reports a rework issue and locks downstream stages.
3. A fully reviewed episode without prompt/video/export paths reports missing prompt and missing artifact issues.
4. CSV export rows contain episode, title, stage labels, and issue labels.

Run:

```bash
cd frontend && pnpm exec vitest run src/components/canvas/productionBoard.test.ts
```

Expected: FAIL because the helper module does not exist.

- [x] **Step 2: Implement helper**

Implement `deriveEpisodeProductionRows`, `summarizeEpisodeProductionRows`, and `buildEpisodeProductionCsv` with no React dependencies.

- [x] **Step 3: Verify helper tests**

Run:

```bash
cd frontend && pnpm exec vitest run src/components/canvas/productionBoard.test.ts
```

Expected: PASS.

### Task 2: Overview board UI and CSV export

**Files:**
- Create: `frontend/src/components/canvas/EpisodeProductionBoard.tsx`
- Modify: `frontend/src/components/canvas/OverviewCanvas.tsx`
- Modify: `frontend/src/components/canvas/OverviewCanvas.test.tsx`
- Modify: `frontend/src/i18n/{zh,en,vi}/dashboard.ts`

- [x] **Step 1: Write failing component tests**

Add tests that render `OverviewCanvas` for a drama project with two episodes, mock `API.getScriptReview`, and assert:
1. The board title, summary counts, per-episode rows, QA blocked, missing prompt, and rework labels render.
2. Clicking “导出生产清单” creates a CSV blob and revokes the object URL.

Run:

```bash
cd frontend && pnpm exec vitest run src/components/canvas/OverviewCanvas.test.tsx
```

Expected: FAIL because the board component is not rendered yet.

- [x] **Step 2: Implement UI**

Add `EpisodeProductionBoard` to overview pages for non-ad projects with episodes. Fetch existing script-review state for each episode, render summary chips, stage columns, issue chips, “打开 E{{episode}}” quick jump buttons, and a CSV export button.

- [x] **Step 3: Verify component tests**

Run:

```bash
cd frontend && pnpm exec vitest run src/components/canvas/OverviewCanvas.test.tsx src/components/canvas/productionBoard.test.ts
```

Expected: PASS.

### Task 3: Final quality gates and push

- [x] Run targeted frontend tests/type/lint/build:

```bash
cd frontend && pnpm exec vitest run src/components/canvas/productionBoard.test.ts src/components/canvas/OverviewCanvas.test.tsx src/api.test.ts src/components/canvas/timeline/ScriptReviewGate.test.tsx src/components/canvas/timeline/localWorkflow.test.ts
cd frontend && pnpm typecheck
cd frontend && pnpm exec eslint src/components/canvas/productionBoard.ts src/components/canvas/productionBoard.test.ts src/components/canvas/EpisodeProductionBoard.tsx src/components/canvas/OverviewCanvas.tsx src/components/canvas/OverviewCanvas.test.tsx src/i18n/zh/dashboard.ts src/i18n/en/dashboard.ts src/i18n/vi/dashboard.ts
cd frontend && pnpm build
```

- [x] Run backend smoke tests to ensure no regression in review state shape:

```bash
uv run pytest tests/test_script_review_workflow_gates.py tests/test_script_review_qa.py -q
```

- [x] Commit and push to `origin phase2-local-workflow-overview`.
