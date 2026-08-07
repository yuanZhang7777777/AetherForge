"""Pydantic 出入参，字段名与 frontend/src/types.ts + api.ts 逐字一致。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- 通用
class CurrentUser(BaseModel):
    role: str


class ProjectInput(BaseModel):
    name: str = Field(..., min_length=1)
    platform: str = ""
    market: str = ""
    seller_tier: Literal["general", "mall"] = "general"
    template: str = ""
    size: str = "1:1"
    resolution: str = "1k"
    global_prompt: str = ""
    ai_recognition_enabled: bool = False


class ProductConfiguration(BaseModel):
    platform: str = ""
    market: str = ""
    seller_tier: Literal["general", "mall"] = "general"
    size: str = "1:1"
    resolution: str = "1k"
    global_prompt: str = ""
    ai_recognition_enabled: bool = False


class PromptTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    content: str = Field(..., min_length=1)


class PromptTemplateItem(BaseModel):
    id: str
    name: str
    content: str
    updatedAt: str


class PromptTemplateList(BaseModel):
    templates: list[PromptTemplateItem] = Field(default_factory=list)


# ---------------------------------------------------------------- 资产
class ProductAsset(BaseModel):
    id: str
    name: str
    image_url: str | None = None
    kind: Literal["image", "txt"]


class UploadImportedItem(BaseModel):
    filename: str
    asset_id: str
    cluster_id: str | None = None


class UploadRejectedItem(BaseModel):
    filename: str
    code: str
    message: str


class UploadResult(BaseModel):
    asset_count: int = 0
    imported: list[UploadImportedItem] = Field(default_factory=list)
    rejected: list[UploadRejectedItem] = Field(default_factory=list)


# ---------------------------------------------------------------- 输出图 / 提示词
class OutputImage(BaseModel):
    id: str
    name: str
    slot: str
    slot_id: str
    slot_order: int
    attempt: int
    version: int
    status: str
    review_status: str = "pending"
    image_url: str | None = None
    failure_reason: str | None = None
    prompt: str | None = None
    prompt_version_id: str | None = None


class ProductPrompt(BaseModel):
    slot_order: int
    slot: str
    text: str
    prompt_version_id: str | None = None
    display_prompt: str | None = None
    read_only: bool | None = None
    decision_task: str | None = None
    conversion_goal: str | None = None
    image_goal: str | None = None
    buyer_question: str | None = None
    creative_angle: str | None = None
    creative_strategy: dict[str, Any] | None = None
    localized_copy: dict[str, Any] | None = None


class CreativeBriefPlan(BaseModel):
    slot_order: int | None = None
    decision_task: str | None = None
    conversion_goal: str | None = None
    main_scene: str | None = None
    main_action: str | None = None
    appearance_ids: list[str] = Field(default_factory=list)


class MarketingPlan(BaseModel):
    plans: list[CreativeBriefPlan] = Field(default_factory=list)


class PreparationInfo(BaseModel):
    status: str
    stage: str | None = None
    current: int = 0
    total: int = 7
    error: str | None = None


class GenerationProgress(BaseModel):
    status: str | None = None
    current: int = 0
    completed: int = 0
    active: int = 0
    failed: int = 0
    total: int = 0


class ProductSku(BaseModel):
    id: str
    name: str
    product_name: str | None = None
    product_name_source: str | None = None
    store_name: str | None = None
    sku: str | None = None
    import_status: str | None = None
    relation_type: str | None = None
    asset_ids: list[str] = Field(default_factory=list)
    assets: list[ProductAsset] = Field(default_factory=list)
    facts: str = ""
    product_facts: str | None = None
    product_style: str | None = None
    identity_lock: str = ""
    brief: str = ""
    preparation_status: str | None = None
    preparation: PreparationInfo | None = None
    generation_progress: GenerationProgress | None = None
    identity: dict[str, Any] | None = None
    fact_ledger: dict[str, Any] | None = None
    marketing_plan: MarketingPlan | None = None
    overrides: dict[str, Any] | None = None
    effective_config: ProductConfiguration | None = None
    version: int = 1
    prompts: list[ProductPrompt] = Field(default_factory=list)
    analysis_snapshot: dict[str, Any] | None = None
    outputs: list[OutputImage] = Field(default_factory=list)


class TemplateSlotInfo(BaseModel):
    order: int
    name: str
    purpose: str


class PreflightFull(BaseModel):
    cluster_count: int = 0
    slot_count: int = 0
    generation_count: int = 0
    blocking_errors: list[str] = Field(default_factory=list)
    template: dict[str, Any] | None = None
    rule_profile: dict[str, Any] | None = None


class Project(BaseModel):
    id: str
    name: str
    platform: str = ""
    market: str = ""
    seller_tier: str | None = None
    configuration_status: str | None = None
    default_config: ProductConfiguration | None = None
    template: str = ""
    size: str = "1:1"
    resolution: str | None = "1k"
    status: str
    assets: list[ProductAsset] = Field(default_factory=list)
    skus: list[ProductSku] = Field(default_factory=list)
    sku_imports: list[dict[str, Any]] = Field(default_factory=list)
    template_slots: list[TemplateSlotInfo] = Field(default_factory=list)
    preflight: PreflightFull | None = None
    updated_at: str


class WorkspaceSnapshot(BaseModel):
    projects: list[Project] = Field(default_factory=list)
    current_user: CurrentUser | None = None


# ---------------------------------------------------------------- 进度
class ProductSkuProgress(BaseModel):
    id: str
    preparation_status: str | None = None
    preparation: PreparationInfo | None = None
    generation_progress: GenerationProgress | None = None
    prompts: list[ProductPrompt] = Field(default_factory=list)
    outputs: list[OutputImage] = Field(default_factory=list)


class ProjectProgress(BaseModel):
    id: str
    status: str
    updated_at: str
    skus: list[ProductSkuProgress] = Field(default_factory=list)


# ---------------------------------------------------------------- 项目操作请求
class PrepareRequest(BaseModel):
    cluster_ids: list[str] = Field(default_factory=list)


class PrepareItem(BaseModel):
    cluster_id: str
    status: str
    stage: str | None = None
    code: str | None = None


class PrepareResult(BaseModel):
    items: list[PrepareItem] = Field(default_factory=list)


class GenerateRequest(BaseModel):
    cluster_ids: list[str] = Field(default_factory=list)
    slot_orders: list[int] = Field(default_factory=list)


class GenerateItem(BaseModel):
    cluster_id: str
    status: str
    code: str | None = None
    message: str | None = None


class GenerateResult(BaseModel):
    generation_count: int = 0
    items: list[GenerateItem] = Field(default_factory=list)


class GenerationActionResponse(BaseModel):
    id: str
    attempt: int
    status: str
    review_status: str | None = None


class ReviewAnnotation(BaseModel):
    kind: str
    points: list[list[float]] | None = None
    rect: list[float] | None = None
    color: str = ""
    width: float = 1.0


class ReviewInput(BaseModel):
    decision: Literal["accept", "changes_requested"]
    issue_tags: list[str] = Field(default_factory=list)
    description: str = ""
    annotations: list[ReviewAnnotation] = Field(default_factory=list)


class RevisionInput(BaseModel):
    issue_tags: list[str] = Field(default_factory=list)
    description: str = ""
    annotations: list[ReviewAnnotation] = Field(default_factory=list)


class PauseRequest(BaseModel):
    cluster_ids: list[str] = Field(default_factory=list)
    generation_ids: list[str] = Field(default_factory=list)


class ExportRequest(BaseModel):
    generation_ids: list[str] = Field(default_factory=list)


class PreflightResult(BaseModel):
    cluster_count: int = 0
    slot_count: int = 0
    generation_count: int = 0
    blocking_errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- cluster 操作
class PromptsItem(BaseModel):
    slot_order: int
    prompt: str | None = None
    display_prompt: str | None = None


class ClusterUpdateInput(BaseModel):
    name: str | None = None
    store_name: str | None = None
    product_facts: str | None = None
    relation_type: str | None = None
    identity_lock: str | None = None
    prompt_override: str | None = None
    platform_override: str | None = None
    market_override: str | None = None
    seller_tier_override: str | None = None
    prompts: list[PromptsItem] | None = None
    asset_order: list[str] | None = None


class ClusterUpdateRequest(ClusterUpdateInput):
    expected_version: int = Field(..., ge=1)


class ClusterUpdateResult(BaseModel):
    id: str
    version: int


class DeleteResult(BaseModel):
    status: str


class MergeRequest(BaseModel):
    asset_id: str
    expected_version: int = Field(..., ge=1)


class SkuImportRequest(BaseModel):
    skus: list[str] = Field(default_factory=list)
    mode: str = "organize"


class SkuImportItem(BaseModel):
    sku: str
    product_name: str | None = None
    status: str
    cluster_id: str | None = None
    error_code: str | None = None


class SkuImportResult(BaseModel):
    imported: int = 0
    failed: int = 0
    items: list[SkuImportItem] = Field(default_factory=list)
