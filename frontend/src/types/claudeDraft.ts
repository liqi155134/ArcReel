export type ClaudeDraftIntent =
  | "script_review_notes"
  | "step1_rewrite_proposal"
  | "production_context_suggestion";

export type ClaudeDraftStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface ClaudeDraftRequest {
  intent: ClaudeDraftIntent;
  episode?: number | null;
  instruction?: string;
  timeout_seconds?: number;
}

export interface ClaudeDraftFinding {
  code?: string;
  message?: string;
  path?: string;
  severity?: string;
  [key: string]: unknown;
}

export interface ClaudeDraftOutput {
  summary: string;
  findings: ClaudeDraftFinding[];
  proposed_patch?: unknown;
  raw_text?: string;
}

export interface ClaudeDraftArtifact {
  schema_version: number;
  artifact_id: string;
  intent: ClaudeDraftIntent;
  project_name: string;
  episode: number | null;
  created_at?: string;
  status: ClaudeDraftStatus;
  context_hash?: string;
  policy?: {
    permission_mode?: string;
    tools?: string[];
    draft_only?: boolean;
    env_scrubbed?: boolean;
    [key: string]: unknown;
  };
  input_summary?: Record<string, unknown>;
  output: ClaudeDraftOutput;
  error?: string;
}
