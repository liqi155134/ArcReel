# Manual Review Package Import/Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add local/manual review package export, Seedance prompt import, and rework brief copy actions to the short-drama workflow panel.

**Architecture:** Keep this client-side and manual-only: derive a JSON review package from existing `ScriptReviewState`, store imported prompt text in component state, and copy/export text through browser APIs. Do not add generation providers, unattended batches, or upstream automation.

**Tech Stack:** React/Vitest, existing ScriptReviewGate local workflow UI, browser Clipboard/Blob APIs, TypeScript.

---

### Task 1: Manual package export utilities and UI

- [x] Write failing UI tests for “导出审核包” and package JSON contents.
- [x] Implement client-side package generation and download action.
- [x] Verify ScriptReviewGate targeted tests pass.

### Task 2: Prompt import and rework brief copy

- [x] Write failing UI tests for “导入 Prompt” and “复制返工说明”.
- [x] Add prompt import textarea/state and copy rework brief action.
- [x] Verify ScriptReviewGate targeted tests pass.

### Task 3: Final verification and push

- [x] Run backend/frontend quality gates.
- [x] Commit and push to personal fork.
