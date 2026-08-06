"""三节点 prepare 管线：识别 → 写提示词 → 就绪。

N1 视觉识别（可选）：项目开启 ai_recognition_enabled 时运行，识别结果与用户填写对比融合，用户填的优先。
N2 写提示词：一次 DeepSeek 调用（think 开）直接产出全部槽位的最终英文提示词 + 整套统一风格（style_brief）。
N3 确定性校验 → READY + fingerprint。

确定性步骤（不额外调模型）：identity_lock 身份锁、fact_ledger 事实台账。
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Cluster
from ..prompts import n1_observe_instruction, n_prompts_system, n_prompts_user
from ..providers import APIMartClient, DeepSeekClient, extract_json
from ..storage import get_storage
from .contract import preparation_fingerprint
from .prompt_compile import _facts, _person_policy, _site, persist_prompts_direct
from .template import global_fallback_template, template_slots

STAGES = ["N1", "N2", "N3"]

_FALLBACK_NAME = "名称待确认"


class PreparationFailed(RuntimeError):
    pass


def _set_stage(db: Session, cluster: Cluster, stage: str, current: int) -> None:
    """推进阶段并提交，让前端 progress 轮询能看到 N1→N3 实时进度。"""
    cluster.preparation_status = "preparing"
    cluster.preparation_stage = stage
    cluster.preparation_current = current
    cluster.preparation_total = len(STAGES)
    db.commit()


def run_cluster_preparation(db: Session, cluster: Cluster, actor_id=None) -> bool:
    """同步执行 prepare 管线。成功 → READY 并写 fingerprint；失败 → FAILED + error。"""
    try:
        _prepare(db, cluster, actor_id)
    except PreparationFailed as exc:
        db.rollback()
        cluster.preparation_status = "failed"
        cluster.preparation_stage = "N3"
        cluster.preparation_current = len(STAGES)
        cluster.preparation_total = len(STAGES)
        cluster.preparation_error = str(exc)
        return False
    except Exception as exc:  # 模型/网络等意外错误
        db.rollback()
        cluster.preparation_status = "failed"
        cluster.preparation_stage = "failed"
        cluster.preparation_current = 0
        cluster.preparation_total = len(STAGES)
        cluster.preparation_error = f"提示词生成失败：{exc}"
        return False
    return True


def _prepare(db: Session, cluster: Cluster, actor_id) -> None:
    _set_stage(db, cluster, "N1", 1)
    # 冻结本组设计的平台/国家，避免 prepare 或生成中途被改设置，导致同一套图语言/风格混杂
    frozen_site = _site(cluster)
    analysis = dict(cluster.analysis_snapshot or {})
    analysis["_preparation_site"] = frozen_site
    cluster.analysis_snapshot = analysis

    if cluster.batch.ai_recognition_enabled:
        _n1_vision_fill(db, cluster)
        _merge_recognition(db, cluster)

    _n2_identity_lock(db, cluster)
    _n3_fact_ledger(cluster)

    _set_stage(db, cluster, "N2", 2)
    style_brief, prompts = _n_prompts(db, cluster, frozen_site)
    analysis = dict(cluster.analysis_snapshot or {})
    analysis["marketing_plan"] = {"plans": [], "style_brief": style_brief}
    cluster.analysis_snapshot = analysis

    created = persist_prompts_direct(db, cluster, prompts, style_brief, actor_id=actor_id)
    if not created:
        raise PreparationFailed("没有可生成的营销槽位")

    _set_stage(db, cluster, "N3", 3)
    _n3_readiness(db, cluster)


# ---------------------------------------------------------------- N1 视觉识别 + 融合
def _clean_product_name(value) -> str:
    text = str(value or "").strip()
    if not text or text == _FALLBACK_NAME or "{{" in text:
        return ""
    return text[:200]


def _n1_vision_fill(db: Session, cluster: Cluster) -> None:
    analysis = dict(cluster.analysis_snapshot or {})
    primary = next(
        (item for item in cluster.cluster_assets if item.role == "primary" and item.asset.kind == "image"),
        None,
    )
    if primary is None:
        analysis["identity"] = {"product_name": "", "observed_identity": "", "reference_quality": 0}
        cluster.analysis_snapshot = analysis
        return
    try:
        with get_storage().local_path(primary.asset.storage_path) as path:
            client = APIMartClient()
            text = client.observe_image(n1_observe_instruction(_FALLBACK_NAME, 1), [path])
        node = _parse_observation(text)
        identity = {
            "product_name": str(node.get("product_name") or ""),
            "observed_identity": str(node.get("observed_identity") or ""),
            "image_role": str(node.get("image_role") or "main_product"),
            "reference_quality": int(node.get("reference_quality") or 0),
            "product_profile": {
                "category": str(node.get("category") or ""),
                "primary_appearance": str(node.get("observed_identity") or ""),
            },
        }
        analysis["identity"] = identity
        analysis["product_name"] = identity["product_name"]
    except Exception:
        analysis["identity"] = {
            "product_name": "",
            "observed_identity": "",
            "reference_quality": 0,
            "note": "视觉识别失败，可手动填写商品信息",
        }
    cluster.analysis_snapshot = analysis


def _parse_observation(text: str) -> dict:
    try:
        node = extract_json(text)
    except Exception:
        node = {}
    if not isinstance(node, dict):
        node = {}
    if not node.get("observed_identity") and isinstance(text, str):
        node["observed_identity"] = text[:2000]
    return node


def _merge_recognition(db: Session, cluster: Cluster) -> None:
    """识别结果与用户填写对比融合：用户填的优先级最高，识别仅补齐用户没填的部分。"""
    analysis = dict(cluster.analysis_snapshot or {})
    identity = dict(analysis.get("identity") or {})
    user_name = (cluster.product_name or "").strip()
    recognized_name = _clean_product_name(identity.get("product_name"))
    recognized_identity = str(identity.get("observed_identity") or "").strip()
    user_facts = (cluster.product_facts or "").strip()

    if user_name:
        analysis["product_name_source"] = "manual"
        identity["product_name"] = user_name
        analysis["product_name"] = user_name
    elif recognized_name:
        cluster.product_name = recognized_name
        analysis["product_name_source"] = "ai"
        analysis["product_name"] = recognized_name

    if user_facts and analysis.get("product_facts_source") != "recognition":
        # 用户手动填过补充信息 → 用户覆盖优先，识别结果仅留备注
        identity["observed_identity"] = user_facts
        if recognized_identity:
            identity["recognition_note"] = recognized_identity[:800]
    elif recognized_identity:
        # 用户没填（或此前是识别自动填充）→ 最新识别结果回填商品卡补充信息，
        # 标记来源以便 _facts 与项目级提示词合并，保留项目风格。
        cluster.product_facts = recognized_identity[:2000]
        identity["observed_identity"] = recognized_identity
        analysis["product_facts_source"] = "recognition"

    analysis["identity"] = identity
    cluster.analysis_snapshot = analysis


# ---------------------------------------------------------------- N2 身份锁（确定性）
def _n2_identity_lock(db: Session, cluster: Cluster) -> None:
    name = (cluster.product_name or "").strip()
    if name:
        lock = f"主商品 {name}，部件/数量/颜色/布局与参考图一致，禁止增减部件、禁止虚构内部结构、禁止混入其他 SKU 属性。"
    else:
        observed = ((cluster.analysis_snapshot or {}).get("identity") or {}).get("observed_identity") or ""
        lock = f"以参考图为准，保持可见商品结构不变：{observed}".strip() if observed else "以参考图为准，保持商品结构、部件、颜色、Logo、接口、排列一致，禁止增减。"
    cluster.identity_lock = lock[:2000]


# ---------------------------------------------------------------- 事实台账（确定性）
def _n3_fact_ledger(cluster: Cluster) -> None:
    facts = []
    for statement in _facts(cluster):
        facts.append(
            {
                "fact_id": f"f-{uuid.uuid4().hex[:8]}",
                "statement": statement,
                "fact_class": "confirmed",
                "confidence": 100,
                "evidence_refs": [],
                "risk_level": "low",
                "allowed_uses": ["copy"],
            }
        )
    cluster.analysis_snapshot["fact_ledger"] = {
        "facts": facts,
        "review_summary": {
            "confirmed_count": len(facts),
            "observed_count": 0,
            "inferred_count": 0,
            "high_risk_count": 0,
        },
    }


# ---------------------------------------------------------------- N2 写提示词（一次 DeepSeek 调用）
def _n_prompts(db: Session, cluster: Cluster, site: str) -> tuple[str, dict[int, str]]:
    template = cluster.batch.output_template or global_fallback_template(db)
    slots = [
        {"order": s.order, "name": s.name}
        for s in template_slots(template)
        if s.name != "Seller original product photo"
    ]
    client = DeepSeekClient()
    result = client.complete_json(
        n_prompts_system(site),
        n_prompts_user(
            (cluster.product_name or cluster.name or "").strip(),
            (cluster.identity_lock or "").strip(),
            _facts(cluster),
            site,
            _person_policy(cluster),
            slots,
        ),
        reasoning_effort=settings.reasoning_effort_deep,
        max_tokens=settings.max_tokens_prompts,
        thinking=True,
    )
    node = result["json"]
    style_brief = str(node.get("style_brief") or "").strip() if isinstance(node, dict) else ""
    raw = node.get("prompts") if isinstance(node, dict) else None
    if not isinstance(raw, list):
        raise PreparationFailed("写提示词未返回 prompts 数组")
    prompts: dict[int, str] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            slot = int(item.get("slot") or 0)
        except (TypeError, ValueError):
            continue
        text = str(item.get("prompt") or "").strip()
        if slot >= 1 and text:
            prompts[slot] = text
    return style_brief, prompts


# ---------------------------------------------------------------- N3 就绪
def _n3_readiness(db: Session, cluster: Cluster) -> None:
    required = ("identity_lock",)
    missing = [field for field in required if not (getattr(cluster, field) or "").strip()]
    if missing:
        raise PreparationFailed(f"缺少必要信息：{', '.join(missing)}")
    analysis = dict(cluster.analysis_snapshot or {})
    analysis["_runtime_contract_fingerprint"] = preparation_fingerprint(cluster.batch, cluster)
    cluster.analysis_snapshot = analysis
    cluster.preparation_status = "ready"
    cluster.preparation_stage = "ready"
    cluster.preparation_current = len(STAGES)
    cluster.preparation_total = len(STAGES)
    cluster.preparation_error = ""
