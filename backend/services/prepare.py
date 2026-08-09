"""三节点 prepare 管线：识别 → 写提示词 → 就绪。

N1 视觉识别（可选）：项目开启 ai_recognition_enabled 时运行，识别结果与用户填写对比融合，用户填的优先。
N2 写提示词：先产出统一风格（style_brief），再按槽位并行产出最终英文提示词 + 中文生图提示词；失败回退旧单次调用。
N3 确定性校验 → READY + fingerprint。

确定性步骤（不额外调模型）：identity_lock 身份锁、fact_ledger 事实台账。
"""
from __future__ import annotations

import uuid
import re
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Cluster
from ..prompts import (
    n1_observe_instruction,
    n_prepare_single_gpt55_system,
    n_prepare_single_gpt55_user,
    n_prompts_slot_system,
    n_prompts_slot_user,
    n_prompts_style_brief_system,
    n_prompts_style_brief_user,
    n_prompts_system,
    n_prompts_user,
)
from ..providers import APIMartClient, DeepSeekClient, extract_json
from ..storage import get_storage
from .contract import preparation_fingerprint
from .prompt_compile import _facts, _normalize_prompt_text, _person_policy, _site, persist_prompts_direct
from .template import global_fallback_template, template_slots

STAGES = ["N1", "N2", "N3"]

_FALLBACK_NAME = "名称待确认"
_IMAGE_FILENAME_RE = re.compile(r"^[^\\/]+\.(?:jpe?g|png|webp|gif|bmp|tiff?)$", re.IGNORECASE)
_SHOPEE_AD_PREFIX = (
    "Create a high-CTR Shopee Southeast Asia marketplace advertising poster, not a clean studio product photo: "
    "bold oversized headline, dense but hierarchical info modules, promo badges, icons, glowing product outline, "
    "speed lines, strong red/yellow/black or orange/blue contrast, product occupies 60-70% of the frame, "
    "designed for mobile shoppers."
)
_MIN_SINGLE_NODE_FINAL_CHARS = 320
_MIN_SINGLE_NODE_ZH_CHARS = 90
_VISIBLE_TEXT_MAX_LINES = 5
_VISIBLE_TEXT_MAX_CHARS = 72
_SIZE_MISSING_DISCLAIMER_RE = re.compile(
    r"(未提供|无参数|沒有參數|没有参数|请查看|請查看|查看商品页|查看商品頁|"
    r"no parameters|not provided|missing parameters|check product page|view product page|"
    r"โปรดดู|ดูรายละเอียดสินค้า|ไม่มีพารามิเตอร์)",
    re.IGNORECASE,
)
_VISIBLE_TEXT_MARKER_RE = re.compile(r"\b(?:VISIBLE\s+TEXT|TEXT\s+RENDERING)\s*:", re.IGNORECASE)
_VISIBLE_TEXT_PLANNING_RE = re.compile(
    r"(render exactly|visible text|target_language_copy|"
    r"quality\s*&\s*trust|quality and trust|pain point|usage steps|size and material|"
    r"detail close-up|main poster|key benefit|lifestyle image|"
    r"主图|核心卖点图|细节特写图|真实使用场景图|痛点解决图|尺寸材质图|使用步骤图|生活方式图|品质信任图)",
    re.IGNORECASE,
)


class PreparationFailed(RuntimeError):
    pass


class PreparationCanceled(RuntimeError):
    pass


def _ensure_claim_current(db: Session, cluster: Cluster, claimed_revision: int | None) -> None:
    if claimed_revision is None:
        return
    row = db.execute(
        select(Cluster.preparation_status, Cluster.analysis_snapshot).where(Cluster.id == cluster.id)
    ).first()
    if row is None:
        raise PreparationCanceled()
    status, analysis = row
    current_revision = int((analysis or {}).get("_preparation_revision", 0))
    if status not in {"pending", "preparing"} or current_revision != claimed_revision:
        raise PreparationCanceled()


def _set_stage(db: Session, cluster: Cluster, stage: str, current: int, claimed_revision: int | None = None) -> None:
    """推进阶段并提交，让前端 progress 轮询能看到 N1→N3 实时进度。"""
    _ensure_claim_current(db, cluster, claimed_revision)
    cluster.preparation_status = "preparing"
    cluster.preparation_stage = stage
    cluster.preparation_current = current
    cluster.preparation_total = len(STAGES)
    db.commit()


def run_cluster_preparation(db: Session, cluster: Cluster, actor_id=None, claimed_revision: int | None = None) -> bool:
    """同步执行 prepare 管线。成功 → READY 并写 fingerprint；失败 → FAILED + error。"""
    try:
        _prepare(db, cluster, actor_id, claimed_revision)
    except PreparationCanceled:
        db.rollback()
        db.refresh(cluster)
        return False
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


def _prepare(db: Session, cluster: Cluster, actor_id, claimed_revision: int | None = None) -> None:
    # 冻结本组设计的平台/国家，避免 prepare 或生成中途被改设置，导致同一套图语言/风格混杂
    frozen_site = _site(cluster)
    analysis = dict(cluster.analysis_snapshot or {})
    analysis["_preparation_site"] = frozen_site
    cluster.analysis_snapshot = analysis

    if settings.prompt_pipeline_mode in {"gpt55_single", "apimart_single"}:
        _prepare_single_gpt55(db, cluster, frozen_site, actor_id, claimed_revision)
        return

    # 名称+补充信息都填全 → 跳过 N1 视觉识别（省一次 APIMart 调用，不覆盖用户填写）；
    # 只缺一项才跑 N1，_merge_recognition 按字段独立只补缺项，永不覆盖用户填写。
    if cluster.batch.ai_recognition_enabled and not (
        _user_product_name(cluster) and (cluster.product_facts or "").strip()
    ):
        _set_stage(db, cluster, "N1", 1, claimed_revision)
        _n1_vision_fill(db, cluster)
        _merge_recognition(db, cluster)

    _n2_identity_lock(db, cluster)
    _n3_fact_ledger(cluster)

    _set_stage(db, cluster, "N2", 2, claimed_revision)
    style_brief, prompts = _n_prompts(db, cluster, frozen_site)
    analysis = dict(cluster.analysis_snapshot or {})
    analysis["marketing_plan"] = {"plans": [], "style_brief": style_brief}
    cluster.analysis_snapshot = analysis

    created = persist_prompts_direct(db, cluster, prompts, style_brief, actor_id=actor_id)
    if not created:
        raise PreparationFailed("没有可生成的营销槽位")

    _set_stage(db, cluster, "N3", 3, claimed_revision)
    _n3_readiness(db, cluster)


def _prepare_single_gpt55(db: Session, cluster: Cluster, site: str, actor_id, claimed_revision: int | None = None) -> None:
    """单节点 prepare：APIMart 提示词模型一次看图并输出 identity/style/prompts。"""
    _set_stage(db, cluster, "N2", 2, claimed_revision)
    style_brief, prompts, node = _gpt55_single_node(db, cluster, site)
    _merge_single_node_identity(cluster, node)
    _n3_fact_ledger(cluster)

    analysis = dict(cluster.analysis_snapshot or {})
    analysis["marketing_plan"] = {
        "plans": [],
        "style_brief": style_brief,
        "mode": settings.prompt_pipeline_mode,
        "model": settings.apimart_prompt_model,
    }
    cluster.analysis_snapshot = analysis

    created = persist_prompts_direct(db, cluster, prompts, style_brief, actor_id=actor_id)
    if not created:
        raise PreparationFailed("APIMart 单节点未返回可生成的营销槽位")

    _set_stage(db, cluster, "N3", 3, claimed_revision)
    _n3_readiness(db, cluster)


# ---------------------------------------------------------------- N1 视觉识别 + 融合
def _clean_product_name(value) -> str:
    text = str(value or "").strip()
    if not text or text == _FALLBACK_NAME or "{{" in text or _IMAGE_FILENAME_RE.match(text):
        return ""
    return text[:200]


def _user_product_name(cluster: Cluster) -> str:
    return _clean_product_name(getattr(cluster, "product_name", ""))


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
    user_name = _user_product_name(cluster)
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
    name = _user_product_name(cluster)
    if name:
        lock = f"主商品 {name}：部件、数量、颜色、布局与参考图一致。"
    else:
        observed = ((cluster.analysis_snapshot or {}).get("identity") or {}).get("observed_identity") or ""
        lock = f"主商品以参考图为准：{observed}".strip() if observed else "主商品以参考图为准：结构、部件、颜色、Logo、接口、排列一致。"
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


# ---------------------------------------------------------------- N2 写提示词（style_brief + 分槽并行，失败回退旧单次调用）
def _n_prompts(db: Session, cluster: Cluster, site: str) -> tuple[str, dict[int, dict]]:
    template = cluster.batch.output_template or global_fallback_template(db)
    slots = [
        {"order": s.order, "name": s.name}
        for s in template_slots(template)
        if s.name != "Seller original product photo"
    ]
    client = DeepSeekClient()
    product_name = _user_product_name(cluster)
    identity_lock = (cluster.identity_lock or "").strip()
    facts = _facts(cluster)
    person_policy = _person_policy(cluster)
    try:
        return _generate_n_prompts_parallel(
            client,
            product_name=product_name,
            identity_lock=identity_lock,
            facts=facts,
            site=site,
            person_policy=person_policy,
            slots=slots,
        )
    except Exception:
        return _generate_n_prompts_single(
            client,
            product_name=product_name,
            identity_lock=identity_lock,
            facts=facts,
            site=site,
            person_policy=person_policy,
            slots=slots,
        )


def _generate_n_prompts_single(
    client: DeepSeekClient,
    *,
    product_name: str,
    identity_lock: str,
    facts: list[str],
    site: str,
    person_policy: str,
    slots: list[dict],
) -> tuple[str, dict[int, dict]]:
    result = client.complete_json(
        n_prompts_system(site),
        n_prompts_user(
            product_name,
            identity_lock,
            facts,
            site,
            person_policy,
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
    prompts: dict[int, dict] = {}
    for item in raw:
        parsed = _prompt_item(item)
        if parsed is None:
            continue
        slot, prompt = parsed
        prompts[slot] = prompt
    return style_brief, prompts


def _generate_n_prompts_parallel(
    client: DeepSeekClient,
    *,
    product_name: str,
    identity_lock: str,
    facts: list[str],
    site: str,
    person_policy: str,
    slots: list[dict],
) -> tuple[str, dict[int, dict]]:
    style_result = client.complete_json(
        n_prompts_style_brief_system(site),
        n_prompts_style_brief_user(product_name, identity_lock, facts, site, person_policy),
        reasoning_effort=settings.reasoning_effort_prompts,
        max_tokens=2048,
        thinking=True,
    )
    style_node = style_result["json"]
    style_brief = str(style_node.get("style_brief") or "").strip() if isinstance(style_node, dict) else ""
    if not style_brief:
        raise PreparationFailed("写提示词未返回 style_brief")

    prompts: dict[int, dict] = {}

    def build(slot: dict) -> tuple[int, dict]:
        result = client.complete_json(
            n_prompts_slot_system(site),
            n_prompts_slot_user(
                product_name=product_name,
                identity_lock=identity_lock,
                facts=facts,
                site=site,
                person_policy=person_policy,
                style_brief=style_brief,
                slot=slot,
            ),
            reasoning_effort=settings.reasoning_effort_prompts,
            max_tokens=settings.max_tokens_compile,
            thinking=True,
        )
        parsed = _prompt_item(result["json"], expected_slot=int(slot.get("order") or 0))
        if parsed is None:
            raise PreparationFailed(f"写提示词缺失槽位 {slot.get('order')}")
        return parsed

    with ThreadPoolExecutor(max_workers=max(1, min(len(slots), 6))) as executor:
        futures = [executor.submit(build, slot) for slot in slots]
        for future in as_completed(futures):
            slot, prompt = future.result()
            prompts[slot] = prompt
    return style_brief, prompts


def _gpt55_single_node(db: Session, cluster: Cluster, site: str) -> tuple[str, dict[int, dict], dict]:
    template = cluster.batch.output_template or global_fallback_template(db)
    slots = [
        {"order": s.order, "name": s.name}
        for s in template_slots(template)
        if s.name != "Seller original product photo"
    ]
    product_name = _user_product_name(cluster)
    facts = _facts(cluster)
    person_policy = _person_policy(cluster)
    client = APIMartClient()
    system_text = n_prepare_single_gpt55_system(site)
    base_user = n_prepare_single_gpt55_user(
        product_name,
        facts,
        site,
        person_policy,
        slots,
        store_name=str(getattr(cluster, "store_name", "") or "").strip(),
    )
    last_issues: list[str] = []
    with ExitStack() as stack:
        image_sources: list[str] = []
        should_send_images = bool(getattr(cluster.batch, "ai_recognition_enabled", False) and not product_name)
        if should_send_images:
            for item in cluster.cluster_assets:
                if item.asset.kind != "image":
                    continue
                try:
                    local = stack.enter_context(get_storage().local_path(item.asset.storage_path))
                    image_sources.append(str(local))
                except Exception:
                    continue
        for attempt in range(2):
            user_text = base_user if attempt == 0 else _single_node_repair_user(base_user, last_issues)
            result = client.complete_json(
                system_text,
                user_text,
                image_sources=image_sources,
                max_tokens=settings.apimart_prompt_max_output_tokens,
            )
            try:
                style_brief, prompts, node = _parse_single_node_result(result.get("json"), slots)
            except PreparationFailed as exc:
                last_issues = [str(exc)]
                if attempt == 0:
                    continue
                raise
            last_issues = _single_node_prompt_quality_issues(
                prompts,
                slots,
                include_preview_issues=attempt == 0,
            )
            if not last_issues:
                return style_brief, prompts, node
    raise PreparationFailed("APIMart 单节点提示词质量不合格：" + "；".join(last_issues))


def _parse_single_node_result(node, slots: list[dict]) -> tuple[str, dict[int, dict], dict]:
    if not isinstance(node, dict):
        raise PreparationFailed("APIMart 单节点未返回 JSON 对象")
    style_brief = str(node.get("style_brief") or "").strip()
    raw = node.get("prompts")
    if not style_brief or not isinstance(raw, list):
        raise PreparationFailed("APIMart 单节点缺少 style_brief 或 prompts")
    prompts: dict[int, dict] = {}
    for item in raw:
        parsed = _prompt_item(item, front_load=False)
        if parsed is None:
            continue
        slot, prompt = parsed
        prompts[slot] = prompt
    missing = [s["order"] for s in slots if s["order"] not in prompts]
    if missing:
        raise PreparationFailed(f"APIMart 单节点缺少槽位：{', '.join(map(str, missing))}")
    return style_brief, prompts, node


def _single_node_prompt_quality_issues(
    prompts: dict[int, dict],
    slots: list[dict],
    *,
    include_preview_issues: bool = True,
) -> list[str]:
    slot_names = {int(s.get("order") or 0): str(s.get("name") or "") for s in slots}
    issues: list[str] = []
    for slot, prompt in sorted(prompts.items()):
        name = slot_names.get(slot, "")
        zh = str(prompt.get("zh") or "").strip()
        final = str(prompt.get("final") or "").strip()
        target_copy = str(prompt.get("target_language_copy") or "").strip()
        visual_final = _strip_visible_text_section(final)
        label = f"槽位 {slot} {name}".strip()

        if len(visual_final) < _MIN_SINGLE_NODE_FINAL_CHARS:
            issues.append(f"{label} final 过短，需要补充构图、商品状态、图形设计和画面细节")
        if include_preview_issues and len(zh) < _MIN_SINGLE_NODE_ZH_CHARS:
            issues.append(f"{label} zh 过短，需要给用户可编辑的完整中文生图提示词")
        if include_preview_issues and prompt.get("_visible_text_issues"):
            issues.append(f"{label} 可见文字不是短文案，需要改成 2-5 行短标题/短卖点/短标注")

        lower_final = visual_final.lower()
        combined = f"{zh}\n{visual_final}\n{target_copy}"
        if slot == 6 or "尺寸" in name or "material" in name.lower():
            if _SIZE_MISSING_DISCLAIMER_RE.search(combined):
                issues.append(f"{label} 把缺失参数写成画面文案，需要改成视觉化尺寸/材质说明")
            if not any(k in lower_final for k in ("arrow", "measurement", "dimension", "length", "width", "height", "depth", "scale", "ruler")):
                issues.append(f"{label} 缺少测量箭头、比例参照或尺寸结构表达")
            if not any(k in lower_final for k in ("material", "texture", "close-up", "close up", "magnified", "callout", "inset", "detail")):
                issues.append(f"{label} 缺少材质/局部放大/引线说明")

        if slot == 7 or "步骤" in name or "usage" in name.lower():
            if not all(f"panel {i}" in lower_final for i in (1, 2, 3)):
                issues.append(f"{label} 必须用 Panel 1、Panel 2、Panel 3 写清不同分镜状态")
    return issues


def _single_node_repair_user(base_user: str, issues: list[str]) -> str:
    issue_text = "\n".join(f"- {issue}" for issue in issues if issue.strip())
    return (
        base_user
        + "\n\n上一次输出不合格，请根据以下问题重新输出完整 JSON，保持同一个商品和同一套 style_brief，可以重写 prompts：\n"
        + issue_text
        + "\n\n要求：不要解释原因；不要只修一个字段；prompts 数组仍必须覆盖全部槽位。"
    )


def _merge_single_node_identity(cluster: Cluster, node: dict) -> None:
    analysis = dict(cluster.analysis_snapshot or {})
    raw_identity = node.get("identity") if isinstance(node.get("identity"), dict) else {}
    identity = dict(analysis.get("identity") or {})
    identity.update(
        {
            "product_name": str(raw_identity.get("product_name") or identity.get("product_name") or ""),
            "observed_identity": str(raw_identity.get("observed_identity") or identity.get("observed_identity") or ""),
            "reference_quality": int(raw_identity.get("reference_quality") or identity.get("reference_quality") or 0),
            "product_profile": {
                **dict(identity.get("product_profile") or {}),
                "category": str(raw_identity.get("category") or ""),
                "primary_appearance": str(raw_identity.get("observed_identity") or ""),
            },
        }
    )
    recognized_name = _clean_product_name(identity.get("product_name"))
    recognized_identity = str(identity.get("observed_identity") or "").strip()
    current_name = _user_product_name(cluster)
    if not current_name and recognized_name:
        cluster.product_name = recognized_name
        analysis["product_name"] = recognized_name
        analysis["product_name_source"] = "ai"
    elif current_name:
        identity["product_name"] = current_name
        analysis["product_name_source"] = "manual"

    if not (cluster.product_facts or "").strip() and recognized_identity:
        cluster.product_facts = recognized_identity[:2000]
        analysis["product_facts_source"] = "recognition"
    elif (cluster.product_facts or "").strip() and recognized_identity:
        identity["recognition_note"] = recognized_identity[:800]

    cluster.identity_lock = str(node.get("identity_lock") or "").strip()[:2000]
    if not cluster.identity_lock:
        _n2_identity_lock(None, cluster)
    analysis["identity"] = identity
    analysis["prompt_pipeline_mode"] = settings.prompt_pipeline_mode
    cluster.analysis_snapshot = analysis


def _prompt_item(item, expected_slot: int | None = None, *, front_load: bool = True) -> tuple[int, dict] | None:
    if not isinstance(item, dict):
        return None
    try:
        slot = int(item.get("slot") or 0)
    except (TypeError, ValueError):
        return None
    if expected_slot is not None and slot != expected_slot:
        return None
    final = _normalize_prompt_text(item.get("final") or item.get("prompt"))
    if slot < 1 or not final:
        return None
    visible_lines, visible_issues = _visible_text_lines_from_item(item)
    target_copy = "\n".join(visible_lines)
    prompt = {
        "final": _front_load_shopee_prompt(final, target_copy, visible_lines) if front_load else _ensure_visible_copy(final, target_copy, visible_lines),
        "zh": _normalize_prompt_text(item.get("zh")),
        "target_language_copy": target_copy,
        "visible_text_lines": visible_lines,
    }
    if visible_issues:
        prompt["_visible_text_issues"] = visible_issues
    return slot, prompt


def _strip_visible_text_section(text: str) -> str:
    match = _VISIBLE_TEXT_MARKER_RE.search(text)
    return (text[: match.start()] if match else text).strip()


def _visible_text_lines_from_item(item: dict) -> tuple[list[str], list[str]]:
    raw_lines = _raw_visible_text_lines(item.get("visible_text_lines"))
    if not raw_lines:
        raw_lines = _raw_visible_text_lines(item.get("target_language_copy"))
    lines: list[str] = []
    issues: list[str] = []
    for raw in raw_lines:
        line = re.sub(r"\s+", " ", raw).strip(" -•*；;，,。")
        if not line:
            continue
        if len(line) > _VISIBLE_TEXT_MAX_CHARS:
            issues.append("too_long")
            continue
        if ":" in line and len(line) > 45:
            issues.append("looks_like_brief")
            continue
        if _VISIBLE_TEXT_PLANNING_RE.search(line):
            issues.append("planning_label")
            continue
        if line not in lines:
            lines.append(line)
    if len(lines) > _VISIBLE_TEXT_MAX_LINES:
        issues.append("too_many_lines")
        lines = lines[:_VISIBLE_TEXT_MAX_LINES]
    if raw_lines and not lines:
        issues.append("no_valid_short_copy")
    return lines, issues


def _raw_visible_text_lines(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            lines.extend(_raw_visible_text_lines(item))
        return lines
    if isinstance(value, dict):
        return []
    text = _normalize_prompt_text(value)
    return [line.strip() for line in text.splitlines() if line.strip()]


def _ensure_visible_copy(final: str, target_copy: str, visible_lines: list[str] | None = None) -> str:
    text = _strip_visible_text_section(final)
    lines = visible_lines if visible_lines is not None else [line for line in target_copy.splitlines() if line.strip()]
    if lines:
        block = "\n".join(lines)
        text += "\nVISIBLE TEXT:\n" + block
    return text


def _front_load_shopee_prompt(final: str, target_copy: str, visible_lines: list[str] | None = None) -> str:
    text = _ensure_visible_copy(final, target_copy, visible_lines)
    if not text.startswith(_SHOPEE_AD_PREFIX):
        text = _SHOPEE_AD_PREFIX + "\n" + text
    return text


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
