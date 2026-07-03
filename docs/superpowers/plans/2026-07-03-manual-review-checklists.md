# Manual Review Checklists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent manual checklist templates for storyboard, video, and export review gates.

**Architecture:** Extend existing `episodes[i].local_workflow_reviews` gate records with a `checklist` object while preserving `reviewed`, `decision`, and `note`. Render each gate's checklist next to its existing manual note/actions and submit it with the explicit reviewer decision.

**Tech Stack:** FastAPI service/router, TypeScript API/types, React/Vitest, pytest/basedpyright/ruff.

---

### Task 1: Backend checklist persistence

- [x] Write failing backend tests for checklist defaults and saving checklist values.
- [x] Extend request/service summary to normalize and persist per-gate checklist values.
- [x] Verify backend targeted tests pass.

### Task 2: Frontend checklist UI

- [x] Write failing frontend tests for checklist payload and visible checklist controls.
- [x] Add checklist types, labels, UI state, and payload submission.
- [x] Verify frontend targeted tests pass.

### Task 3: Final verification and push

- [x] Run backend tests/type/lint.
- [x] Run frontend tests/type/lint/build.
- [x] Commit and push to personal fork.
