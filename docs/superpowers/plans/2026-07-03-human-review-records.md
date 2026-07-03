# Human Review Records Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace plain manual gate checkmarks with richer human-in-the-loop review records for storyboard/video/export gates.

**Architecture:** Keep current per-episode local workflow storage under `episodes[i].local_workflow_reviews`. Extend each gate record with `decision` and `note`, while preserving existing `reviewed` compatibility. Frontend remains manual-only: no auto-generation, no market automation, no unattended batch.

**Tech Stack:** FastAPI service/router, TypeScript API/types, React/Vitest.

---

### Task 1: Backend review decision/note persistence

- [x] Write failing tests for saving `decision="needs_changes"` and note on storyboard gate.
- [x] Extend backend request/service to persist `decision` and `note`.
- [x] Verify backend targeted tests pass.

### Task 2: Frontend API/types and UI

- [x] Write failing frontend tests for API payload and ScriptReviewGate note/decision UI.
- [x] Add `decision`/`note` types and UI controls.
- [x] Verify frontend targeted tests pass.

### Task 3: Final verification and push

- [x] Run backend tests/type/lint.
- [x] Run frontend tests/type/lint/build.
- [x] Commit and push to personal fork.
