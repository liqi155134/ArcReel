# Review Rework Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn manual `needs_changes` review records into an actionable rework loop with visible blockers, locked downstream gates, and a manual “mark fixed / resubmit for review” action.

**Architecture:** Keep the existing per-episode `local_workflow_reviews` storage and `setScriptReviewWorkflowGate` API. Extend frontend workflow state derivation to accept gate decisions and treat `needs_changes` as a warning/blocking stage; render a current-blocker summary and a reset-to-pending action that preserves checklist values while clearing the rework note.

**Tech Stack:** TypeScript local workflow derivation, React/Vitest UI, existing FastAPI review gate endpoint.

---

### Task 1: Workflow status derivation

- [x] Write failing tests showing storyboard/video `needs_changes` marks that gate as warning and locks downstream stages.
- [x] Extend `deriveLocalWorkflowStages` input with gate decisions.
- [x] Verify local workflow tests pass.

### Task 2: Rework loop UI

- [x] Write failing UI tests for current blocker copy, failed checklist summary, and “mark fixed / resubmit” action.
- [x] Render a rework summary panel and reset action for the first `needs_changes` gate.
- [x] Verify ScriptReviewGate tests pass.

### Task 3: Final verification and push

- [x] Run backend/frontend targeted and full quality gates.
- [x] Commit and push to personal fork.
