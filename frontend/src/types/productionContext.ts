export interface ProductionProjectBible {
  logline: string;
  audience: string;
  tone: string;
  visual_style: string;
  world_rules: string;
  character_anchors: string[];
  scene_anchors: string[];
  prop_anchors: string[];
  negative_constraints: string[];
  [key: string]: unknown;
}

export interface ProductionStepContext {
  manual_opt_in_only: boolean;
  include_project_bible: boolean;
  include_previous_step: boolean;
  include_revision_memory: boolean;
  include_acceptance_checklist: boolean;
  [key: string]: unknown;
}

export interface ProductionAcceptanceChecklistItem {
  id?: string;
  label: string;
  checked: boolean;
  [key: string]: unknown;
}

export interface ProductionRevisionMemory {
  id?: string;
  created_at?: string;
  step?: string;
  shot_id?: string;
  failure_category?: string;
  previous_prompt?: string;
  human_critique?: string;
  next_fix_strategy?: string;
  before_after_versions?: unknown[];
  acceptance_checklist?: unknown[];
  [key: string]: unknown;
}

export interface ProductionContext {
  schema_version: number;
  project_bible: ProductionProjectBible;
  step_context: ProductionStepContext;
  revision_memory: ProductionRevisionMemory[];
  acceptance_checklist: ProductionAcceptanceChecklistItem[];
}

export interface ProductionContextPayload {
  project_bible?: Partial<ProductionProjectBible>;
  step_context?: Partial<ProductionStepContext>;
  revision_memory?: ProductionRevisionMemory[];
  acceptance_checklist?: ProductionAcceptanceChecklistItem[];
  [key: string]: unknown;
}

export interface ProductionContextResponse {
  context: ProductionContext;
}

export interface SaveProductionContextResponse {
  success: boolean;
  context: ProductionContext;
}

export interface AppendProductionRevisionResponse {
  success: boolean;
  revision: ProductionRevisionMemory;
  context: ProductionContext;
}

export interface ProductionContextSnippetResponse {
  snippet: string;
}
