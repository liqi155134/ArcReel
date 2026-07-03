# Phase 2 Manual Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Persist local/manual production gate state so the workflow overview can unlock video/export steps from explicit user review, not automation.

**Architecture:** Store per-episode local workflow reviews inside `project.json` under each episode entry. Keep it manual and local: no provider changes, no market automation, no unattended batch. Extend existing script-review service/router because it already owns step1→step2 review state and returns the gate state consumed by `ScriptReviewGate`.

**Tech Stack:** FastAPI service/router, ProjectManager metadata updates, TypeScript API/types, React/Vitest.

---

### Task 1: Backend local workflow gate state

**Files:**
- Modify: `server/services/script_review.py`
- Modify: `server/routers/script_review.py`
- Test: `tests/test_script_review_workflow_gates.py`

- [x] **Step 1: Write failing service tests**

Test that `get_state()` returns `local_workflow_reviews.storyboard_reviewed === false` by default, `set_workflow_review(..., gate="storyboard", reviewed=True)` persists true with `reviewed_at`, and unsetting returns false.

Run: `uv run pytest tests/test_script_review_workflow_gates.py -q`
Expected: FAIL because the service method/field does not exist.

- [x] **Step 2: Implement service/router**

Add `local_workflow_reviews` to state and `PUT /script-review/workflow-gates/{gate}` for `storyboard` / `video` / `export` review flags.

- [x] **Step 3: Verify backend**

Run: `uv run pytest tests/test_script_review_workflow_gates.py tests/test_script_review_qa.py tests/test_script_review_router.py -q`
Expected: PASS.

### Task 2: Frontend API/types and workflow derivation

**Files:**
- Modify: `frontend/src/types/script.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.test.ts`
- Modify: `frontend/src/components/canvas/timeline/localWorkflow.ts`
- Modify: `frontend/src/components/canvas/timeline/localWorkflow.test.ts`

- [x] **Step 1: Write failing frontend tests**

Cover API path encoding and that storyboard-reviewed only unlocks video after script is confirmed.

- [x] **Step 2: Implement types/API/helper**

Add `local_workflow_reviews` to `ScriptReviewState`, add API wrapper, and feed review flags into workflow derivation.

- [x] **Step 3: Verify frontend unit tests**

Run: `cd frontend && pnpm exec vitest run src/api.test.ts src/components/canvas/timeline/localWorkflow.test.ts`
Expected: PASS.

### Task 3: ScriptReviewGate manual action

**Files:**
- Modify: `frontend/src/components/canvas/timeline/ScriptReviewGate.tsx`
- Modify: `frontend/src/components/canvas/timeline/ScriptReviewGate.test.tsx`
- Modify: `frontend/src/i18n/{zh,en,vi}/dashboard.ts`

- [x] **Step 1: Write failing component tests**

When script is confirmed and storyboard is not reviewed, render a manual “mark storyboard reviewed” action; clicking calls the new API and updates state. When reviewed, render reviewed status.

- [x] **Step 2: Implement UI**

Add a manual action in the workflow overview only. No batch action and no automatic generation.

- [x] **Step 3: Verify component tests**

Run: `cd frontend && pnpm exec vitest run src/components/canvas/timeline/ScriptReviewGate.test.tsx src/components/canvas/timeline/localWorkflow.test.ts`
Expected: PASS.

### Task 4: Final verification and push

- [x] Run changed frontend tests, typecheck, eslint, build.
- [x] Run backend targeted tests, basedpyright, ruff.
- [x] Commit and push to `origin phase2-local-workflow-overview`.
