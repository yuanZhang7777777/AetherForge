"""SQLAlchemy 实体映射，对齐 picturesGenerate Django models 的字段与约束。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(254), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="operator")
    daily_generation_limit: Mapped[int] = mapped_column(Integer, default=100)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @property
    def is_platform_admin(self) -> bool:
        return self.role == "admin"


class OutputTemplate(Base):
    __tablename__ = "output_templates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    seed_key: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    platform: Mapped[str] = mapped_column(String(40))
    site: Mapped[str] = mapped_column(String(40), default="")
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(40), default="v1")
    status: Mapped[str] = mapped_column(String(20), default="published")
    default_size: Mapped[str] = mapped_column(String(20), default="1:1")
    default_resolution: Mapped[str] = mapped_column(String(20), default="1k")

    slots: Mapped[list["OutputSlot"]] = relationship(
        back_populates="template", order_by="OutputSlot.order", cascade="all, delete-orphan"
    )


class OutputSlot(Base):
    __tablename__ = "output_slots"
    __table_args__ = (
        UniqueConstraint("template_id", "order", name="unique_template_slot_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("output_templates.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    order: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(Text, default="")

    template: Mapped["OutputTemplate"] = relationship(back_populates="slots")


class UserPromptTemplate(Base):
    __tablename__ = "user_prompt_templates"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="unique_user_prompt_template_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    user: Mapped["User"] = relationship()


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    platform: Mapped[str] = mapped_column(String(40), default="generic")
    site: Mapped[str] = mapped_column(String(40), default="SEA")
    market: Mapped[str] = mapped_column(String(40), default="SEA")
    seller_tier: Mapped[str] = mapped_column(String(20), default="general")
    output_template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("output_templates.id", ondelete="RESTRICT"), nullable=True
    )
    size: Mapped[str] = mapped_column(String(20), default="1:1")
    resolution: Mapped[str] = mapped_column(String(20), default="1k")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    global_prompt: Mapped[str] = mapped_column(Text, default="")
    ai_recognition_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_generation_key: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, unique=True, nullable=True
    )
    last_import_mode: Mapped[str] = mapped_column(String(20), default="organize")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    owner: Mapped["User"] = relationship()
    output_template: Mapped["OutputTemplate | None"] = relationship()
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )
    clusters: Mapped[list["Cluster"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )
    generations: Mapped[list["Generation"]] = relationship(back_populates="batch")

    def recompute_status(self) -> str:
        generations = list(self.generations)
        if not generations:
            return self.status
        statuses = {g.status for g in generations}
        completed = {g for g in generations if g.status == "completed"}
        terminal_bad = {g.status for g in generations if g.status in {"failed", "canceled"}}
        if statuses == {"completed"}:
            self.status = "completed"
        elif terminal_bad and completed:
            self.status = "partial"
        elif statuses <= {"failed", "canceled"}:
            self.status = "failed"
        else:
            self.status = "running"
        return self.status


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(10))  # image | txt
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    file_size: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(100))
    validation_status: Mapped[str] = mapped_column(String(20), default="valid")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_content: Mapped[str] = mapped_column(Text, default="")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    batch: Mapped["Batch"] = relationship(back_populates="assets")
    cluster_asset: Mapped["ClusterAsset | None"] = relationship(
        back_populates="asset", uselist=False, cascade="all, delete-orphan"
    )


class Cluster(Base):
    __tablename__ = "clusters"
    __table_args__ = (
        UniqueConstraint("batch_id", "sku", name="unique_batch_sku"),
        Index("cluster_prep_queue_idx", "preparation_status", "updated_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    sku: Mapped[str | None] = mapped_column(String(120), nullable=True)
    product_name: Mapped[str] = mapped_column(String(200), default="")
    product_facts: Mapped[str] = mapped_column(Text, default="")
    identity_lock: Mapped[str] = mapped_column(Text, default="")
    target_consumer: Mapped[str] = mapped_column(String(40), default="")
    prompt_override: Mapped[str] = mapped_column(Text, default="")
    platform_override: Mapped[str | None] = mapped_column(String(40), nullable=True)
    market_override: Mapped[str | None] = mapped_column(String(40), nullable=True)
    seller_tier_override: Mapped[str | None] = mapped_column(String(20), nullable=True)
    relation_type: Mapped[str] = mapped_column(String(40), default="single_product")
    preparation_status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    preparation_error: Mapped[str] = mapped_column(Text, default="")
    preparation_stage: Mapped[str] = mapped_column(String(20), default="draft")
    preparation_current: Mapped[int] = mapped_column(Integer, default=0)
    preparation_total: Mapped[int] = mapped_column(Integer, default=7)
    analysis_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    auto_generate: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    batch: Mapped["Batch"] = relationship(back_populates="clusters")
    cluster_assets: Mapped[list["ClusterAsset"]] = relationship(
        back_populates="cluster",
        order_by="ClusterAsset.order",
        cascade="all, delete-orphan",
    )
    generations: Mapped[list["Generation"]] = relationship(back_populates="cluster")


class ClusterAsset(Base):
    __tablename__ = "cluster_assets"
    __table_args__ = (
        UniqueConstraint("cluster_id", "order", name="unique_cluster_asset_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), unique=True
    )
    role: Mapped[str] = mapped_column(String(20))  # primary | reference
    order: Mapped[int] = mapped_column(Integer, default=1)

    cluster: Mapped["Cluster"] = relationship(back_populates="cluster_assets")
    asset: Mapped["Asset"] = relationship(back_populates="cluster_asset")


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), index=True
    )
    output_slot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("output_slots.id", ondelete="RESTRICT"), nullable=True
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    node_name: Mapped[str] = mapped_column(String(80), default="slot_prompt")
    template_version: Mapped[str] = mapped_column(String(40), default="builtin-v1")
    provider_model: Mapped[str] = mapped_column(String(80), default="gpt-image-2")
    prompt_text: Mapped[str] = mapped_column(Text)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    structured_output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evaluation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    cluster: Mapped["Cluster"] = relationship()
    output_slot: Mapped["OutputSlot | None"] = relationship()
    generations: Mapped[list["Generation"]] = relationship(back_populates="prompt_version")


class Generation(Base):
    __tablename__ = "generations"
    __table_args__ = (
        UniqueConstraint("cluster_id", "output_slot_id", "attempt", name="unique_generation_attempt"),
        Index("generation_queue_idx", "status", "created_at", "id"),
        Index("generation_poll_idx", "status", "submitted_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"), index=True
    )
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), index=True
    )
    output_slot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("output_slots.id", ondelete="RESTRICT")
    )
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"), nullable=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    prompt_text: Mapped[str] = mapped_column(Text, default="")
    size: Mapped[str] = mapped_column(String(20), default="1:1")
    resolution: Mapped[str] = mapped_column(String(20), default="1k")
    provider_task_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    provider_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reference_snapshot: Mapped[list[Any]] = mapped_column(JSON, default=list)
    template_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rule_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    batch: Mapped["Batch"] = relationship(back_populates="generations")
    cluster: Mapped["Cluster"] = relationship(back_populates="generations")
    output_slot: Mapped["OutputSlot"] = relationship()
    prompt_version: Mapped["PromptVersion | None"] = relationship(back_populates="generations")
    result_assets: Mapped[list["ResultAsset"]] = relationship(
        back_populates="generation", cascade="all, delete-orphan"
    )


class ResultAsset(Base):
    __tablename__ = "result_assets"
    __table_args__ = (
        UniqueConstraint("storage_path", name="unique_result_storage_path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    generation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("generations.id", ondelete="CASCADE"), index=True
    )
    storage_path: Mapped[str] = mapped_column(String(500))
    source_url: Mapped[str] = mapped_column(String(500), default="")
    sha256: Mapped[str] = mapped_column(String(64))
    file_size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    generation: Mapped["Generation"] = relationship(back_populates="result_assets")


class SkuImportItem(Base):
    __tablename__ = "sku_import_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "sku", "attempt", name="unique_sku_import_attempt"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"), index=True
    )
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clusters.id", ondelete="SET NULL"), nullable=True
    )
    sku: Mapped[str] = mapped_column(String(120))
    attempt: Mapped[int] = mapped_column(Integer)
    product_name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20))  # imported | failed
    error_message: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DailyGenerationUsage(Base):
    __tablename__ = "daily_generation_usage"
    __table_args__ = (
        Index("uq_daily_org_date", "date", unique=True,
              postgresql_where=text("scope = 'org'"), sqlite_where=text("scope = 'org'")),
        Index("uq_daily_user_date_user", "date", "user_id", unique=True,
              postgresql_where=text("scope = 'user'"), sqlite_where=text("scope = 'user'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(10))  # org | user
    date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    used: Mapped[int] = mapped_column(Integer, default=0)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(80))
    object_type: Mapped[str] = mapped_column(String(80))
    object_id: Mapped[str] = mapped_column(String(80), default="")
    extra: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
