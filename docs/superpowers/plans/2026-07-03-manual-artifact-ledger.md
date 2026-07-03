# Manual Artifact Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist Seedance prompts and manually produced short-drama artifacts for storyboard, video, and export stages inside ArcReel's local production workflow.

**Architecture:** Store a small per-episode `local_workflow_artifacts` object in `project.json`, separate from review decisions but returned with the existing script-review state. Add one explicit manual-save endpoint and UI controls for prompt/artifact paths, notes, export package inclusion, and pasted package JSON import. No new provider integration, no automatic generation, no unattended batch.

**Tech Stack:** FastAPI service/router, ProjectManager metadata updates, TypeScript API/types, React/Vitest, pytest/basedpyright/ruff.

---

### Task 1: Backend persisted artifact ledger

**Files:**
- Modify: `server/services/script_review.py`
- Modify: `server/routers/script_review.py`
- Test: `tests/test_script_review_workflow_gates.py`

- [x] **Step 1: Write failing backend tests**

Add tests that assert `get_state()` returns a default `local_workflow_artifacts` object and that saving a prompt plus storyboard/video/export artifact records persists to `episodes[0].local_workflow_artifacts`.

Run:

```bash
uv run pytest tests/test_script_review_workflow_gates.py::test_get_state_defaults_local_workflow_artifacts tests/test_script_review_workflow_gates.py::test_set_workflow_artifacts_persists_prompt_and_manual_artifacts -q
```

Expected: FAIL because `local_workflow_artifacts` and `set_workflow_artifacts` do not exist yet.

- [x] **Step 2: Implement service/router**

Add `ScriptReviewService.set_workflow_artifacts(project_name, episode, seedance_prompt, artifacts)`, normalize string fields, store under `episodes[i].local_workflow_artifacts`, return latest `get_state()`, and expose `PUT /projects/{project_name}/episodes/{episode}/script-review/workflow-artifacts`.

- [x] **Step 3: Verify backend**

Run:

```bash
uv run pytest tests/test_script_review_workflow_gates.py -q
```

Expected: PASS.

### Task 2: Frontend API/types and manual ledger UI

**Files:**
- Modify: `frontend/src/types/script.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.test.ts`
- Modify: `frontend/src/components/canvas/timeline/ScriptReviewGate.tsx`
- Modify: `frontend/src/components/canvas/timeline/ScriptReviewGate.test.tsx`
- Modify: `frontend/src/i18n/{zh,en,vi}/dashboard.ts`

- [x] **Step 1: Write failing frontend tests**

Add tests for:
1. `API.setScriptReviewWorkflowArtifacts()` encodes path and sends prompt/artifact payload.
2. The workflow UI saves Seedance Prompt plus manual artifact paths/notes via the new API.
3. Exported review packages include persisted `local_workflow_artifacts`.
4. Pasted package JSON import applies prompt/artifact values through the new API.

Run:

```bash
cd frontend && pnpm exec vitest run src/api.test.ts src/components/canvas/timeline/ScriptReviewGate.test.tsx
```

Expected: FAIL because the API wrapper, types, and UI controls do not exist yet.

- [x] **Step 2: Implement frontend types/API/UI**

Add `ScriptReviewLocalWorkflowArtifacts`, `LocalWorkflowArtifactRecord`, and `LocalWorkflowArtifactsUpdate` types; add API wrapper; initialize UI state from `state.local_workflow_artifacts`; add manual ledger fields, save action, package JSON paste/import action, and include artifacts in exported review package.

- [x] **Step 3: Verify frontend targeted tests**

Run:

```bash
cd frontend && pnpm exec vitest run src/api.test.ts src/components/canvas/timeline/ScriptReviewGate.test.tsx
```

Expected: PASS.

### Task 3: Final quality gates and push

- [x] Run backend tests/type/lint:

```bash
uv run pytest tests/test_script_review_workflow_gates.py tests/test_script_review.py tests/test_script_review_router.py tests/test_script_review_qa.py tests/test_short_drama_qa.py tests/test_text_generation_review_qa.py tests/prompt_rules/test_short_drama_standards.py tests/prompt_rules/test_subagent_md_sync.py -q
uv run basedpyright server/services/script_review.py server/routers/script_review.py tests/test_script_review_workflow_gates.py tests/test_script_review_qa.py tests/test_script_review_router.py
uv run ruff check server/services/script_review.py server/routers/script_review.py tests/test_script_review_workflow_gates.py tests/test_script_review_qa.py tests/test_script_review_router.py
```

- [x] Run frontend tests/type/lint/build:

```bash
cd frontend && pnpm exec vitest run src/api.test.ts src/components/canvas/timeline/ScriptReviewGate.test.tsx src/components/canvas/timeline/localWorkflow.test.ts
cd frontend && pnpm typecheck
cd frontend && pnpm exec eslint src/api.ts src/api.test.ts src/types/script.ts src/components/canvas/timeline/ScriptReviewGate.tsx src/components/canvas/timeline/ScriptReviewGate.test.tsx src/components/canvas/timeline/localWorkflow.ts src/components/canvas/timeline/localWorkflow.test.ts src/i18n/zh/dashboard.ts src/i18n/en/dashboard.ts src/i18n/vi/dashboard.ts
cd frontend && pnpm build
```

- [x] Commit and push to `origin phase2-local-workflow-overview`.
