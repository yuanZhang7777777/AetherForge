export type GenerationStatus = "draft" | "queued" | "running" | "completed" | "failed";
export type ReviewStatus = "pending" | "accepted" | "changes_requested" | "rejected";
export type ReviewDecision = "accept" | "changes_requested";
export type ImportMode = "auto" | "organize";
export type RelationType = "single_product" | "same_product" | "variant_group";

export interface ProductAsset {
  id: string;
  name: string;
  imageUrl?: string;
  kind: "image" | "txt";
}

export interface OutputImage {
  id: string;
  name: string;
  slot: string;
  slotId: string;
  slotOrder: number;
  attempt: number;
  version: number;
  status: GenerationStatus;
  reviewStatus: ReviewStatus;
  imageUrl?: string;
  failureReason?: string;
  prompt?: string;
}

export interface ProductPrompt {
  slotOrder: number;
  slot: string;
  text: string;
  displayPrompt?: string;
  readOnly?: boolean;
  decisionTask?: string;
  conversionGoal?: string;
  creativeStrategy?: {
    mode?: string;
    userJob?: string;
    consumerBenefit?: string;
    mentalSimulation?: string;
    emotionalShift?: string;
    productVoice?: string;
    identitySignal?: string;
  };
  localizedCopy?: {
    language?: string;
    lines?: string[];
  };
}

export type PromptFactClass = "confirmed" | "observed" | "inferred";

export interface PromptFact {
  fact_id: string;
  statement: string;
  fact_class: PromptFactClass;
  confidence: number;
  evidence_refs: string[];
  risk_level: string;
  allowed_uses: string[];
  review_note?: string;
}

export interface FactLedgerSnapshot {
  facts?: PromptFact[];
  review_summary?: {
    confirmed_count: number;
    observed_count: number;
    inferred_count: number;
    high_risk_count: number;
  };
  blocked_claim_topics?: string[];
}

export type RuleGateMessage = string | {
  message?: string;
  reason?: string;
  statement?: string;
  rule_id?: string;
};

export interface RuleGateSnapshot {
  decision?: "pass" | "block";
  hard_blocks?: RuleGateMessage[];
  semantic_risks?: RuleGateMessage[];
  warnings?: RuleGateMessage[];
}

export interface PromptAnalysisSnapshot {
  fact_ledger?: FactLedgerSnapshot;
  rule_gate?: RuleGateSnapshot;
  readiness?: { status?: string; code?: string; required_fields?: string[] };
}

export interface SkuImportItem {
  sku: string;
  productName?: string;
  status: "imported" | "failed";
  clusterId?: string | null;
  errorCode?: string | null;
}

export interface SkuImportResult {
  imported: number;
  failed: number;
  items: SkuImportItem[];
}

export interface ClusterUpdateInput {
  name?: string;
  store_name?: string;
  product_facts?: string;
  relation_type?: RelationType;
  identity_lock?: string;
  prompt_override?: string;
  platform_override?: string | null;
  market_override?: string | null;
  seller_tier_override?: "general" | "mall" | null;
  prompts?: { slot_order: number; prompt?: string; display_prompt?: string }[];
  asset_order?: string[];
}

export interface ClusterUpdateResult {
  id: string;
  version: number;
}

export interface ProductConfiguration {
  platform: string;
  market: string;
  sellerTier: "general" | "mall";
  size: string;
  resolution: string;
  globalPrompt: string;
  aiRecognitionEnabled?: boolean;
}

export interface PromptTemplate {
  id: string;
  name: string;
  content: string;
  updatedAt?: string;
}

export interface ProductOverrides {
  platform: string | null;
  market: string | null;
  sellerTier: "general" | "mall" | null;
}

export interface ProductSku {
  id: string;
  name: string;
  storeName?: string;
  productNameSource?: "ai" | "manual" | "erp" | "blank";
  sku?: string;
  relationType?: RelationType;
  assetIds: string[];
  assets?: ProductAsset[];
  facts: string;
  productFacts?: string;
  productStyle?: string;
  identityLock: string;
  brief: string;
  preparationStatus?: string;
  preparation?: {
    status: string;
    stage?: string;
    current: number;
    total: number;
    error?: string;
  };
  generationProgress?: { status?: string; current?: number; completed?: number; active?: number; failed?: number; total: number };
  identity?: {
    product_name?: string;
    confidence?: number;
    product_profile?: {
      category?: string;
      primary_appearance?: string;
      shared_structure?: string[];
      included_items?: string[];
    };
    identity_lock?: { must_not_change?: string[]; family_invariants?: string[] };
    target_appearances?: {
      appearance_id: string;
      label?: string;
      variant_attributes?: string[];
      asset_ids: string[];
      primary_asset_id: string;
    }[];
  };
  marketingPlan?: { plans?: CreativeBriefPlan[] };
  overrides?: ProductOverrides;
  effectiveConfig?: ProductConfiguration;
  version: number;
  prompts?: ProductPrompt[];
  analysisSnapshot?: PromptAnalysisSnapshot;
  outputs: OutputImage[];
}

export interface Project {
  id: string;
  name: string;
  platform: string;
  market: string;
  sellerTier?: "general" | "mall";
  configurationStatus?: "required" | "configured";
  defaultConfig?: ProductConfiguration;
  template: string;
  size: string;
  resolution?: string;
  status: GenerationStatus;
  assets: ProductAsset[];
  skus: ProductSku[];
  updatedAt: string;
}

export interface ProductSkuProgress {
  id: string;
  preparationStatus?: string;
  preparation?: ProductSku["preparation"];
  generationProgress?: ProductSku["generationProgress"];
  prompts?: ProductPrompt[];
  outputs: OutputImage[];
}

export interface ProjectProgress {
  id: string;
  status: GenerationStatus;
  updatedAt: string;
  skus: ProductSkuProgress[];
}

export interface WorkspaceSnapshot {
  projects: Project[];
  currentUser?: CurrentUser;
}

export interface CurrentUser {
  role: "admin" | "operator";
}

export interface CreativeBriefPlan {
  slot_order?: number;
  decision_task?: string;
  conversion_goal?: string;
  main_scene?: string;
  main_action?: string;
  appearance_ids?: string[];
}

export interface PromptNodeTemplate {
  id: string;
  node_name: string;
  version: string;
  status: "draft" | "published" | "retired";
  instruction: string;
  user_message_template?: string;
  output_schema: unknown;
  model?: string | null;
  platform_scope?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PromptNodeDraftInput {
  node_name: string;
  version: string;
  instruction: string;
  user_message_template?: string;
  output_schema: unknown;
}

export interface ProjectInput {
  name: string;
  platform?: string;
  market?: string;
  seller_tier?: "general" | "mall";
  template?: string;
  size?: string;
  resolution?: string;
  global_prompt?: string;
}

export interface ReviewAnnotation {
  kind: "circle" | "rect" | "stroke";
  points?: number[][];
  rect?: [number, number, number, number];
  color: string;
  width: number;
  note?: string;
}

export interface ReviewInput {
  decision: ReviewDecision;
  issue_tags: string[];
  description: string;
  annotations: ReviewAnnotation[];
}

export interface RevisionInput {
  issue_tags: string[];
  description: string;
  annotations: ReviewAnnotation[];
}

export interface PreflightResult {
  cluster_count: number;
  slot_count: number;
  generation_count: number;
  blocking_errors: string[];
}
