# Phase 2 Local Workflow Overview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a thin LocalMiniDrama-inspired production workflow overview in ArcReel that makes short-drama gates visible for personal/local production.

**Architecture:** Keep ArcReel backend/provider/task queue unchanged. Add a pure frontend helper that derives stage cards from existing project/script-review data, then render it inside the existing ScriptReviewGate so the operator sees where they are before expensive generation.

**Tech Stack:** TypeScript, React, Vitest, existing ArcReel frontend component/test setup.

---

### Task 1: Derive local short-drama workflow stages

**Files:**
- Create: `frontend/src/components/canvas/timeline/localWorkflow.ts`
- Test: `frontend/src/components/canvas/timeline/localWorkflow.test.ts`

- [x] **Step 1: Write failing tests**

Create tests for:
1. QA blocked -> `script_gate` is blocked and video stages are locked.
2. QA warning -> `script_gate` is warning, storyboard stage ready, video stage locked until storyboard review.
3. Confirmed script + storyboard flag -> video stage ready.

Run: `cd frontend && pnpm test -- localWorkflow.test.ts`
Expected: FAIL because module does not exist.

- [x] **Step 2: Implement helper**

Implement `deriveLocalWorkflowStages(input)` as a pure function returning ordered stages:
`brief_gate`, `script_gate`, `asset_gate`, `storyboard_gate`, `video_gate`, `export_gate`.

- [x] **Step 3: Verify helper**

Run: `cd frontend && pnpm test -- localWorkflow.test.ts`
Expected: PASS.

### Task 2: Surface workflow overview in ScriptReviewGate

**Files:**
- Modify: `frontend/src/components/canvas/timeline/ScriptReviewGate.tsx`
- Modify: `frontend/src/components/canvas/timeline/ScriptReviewGate.test.tsx`
- Modify translations: `frontend/src/i18n/{zh,en,vi}/dashboard.ts`

- [x] **Step 1: Write failing component test**

Add a test that renders script review state with QA blocked and asserts the workflow overview shows Script review as blocked and Video generation as locked.

Run: `cd frontend && pnpm test -- ScriptReviewGate.test.tsx`
Expected: FAIL because the overview does not render yet.

- [x] **Step 2: Render minimal overview**

Render a compact stage list above the QA panel. No new API. No batch actions. No provider changes.

- [x] **Step 3: Verify component**

Run: `cd frontend && pnpm test -- ScriptReviewGate.test.tsx localWorkflow.test.ts`
Expected: PASS.

### Task 3: Final verification and push to personal fork

- [x] Run frontend targeted tests, typecheck, eslint, build.
- [x] Run backend Phase 1 targeted tests to ensure no regression.
- [x] Commit with `feat(short-drama): add local workflow overview`.
- [x] Push to `origin phase2-local-workflow-overview` or current personal branch.
