"""generation-worker：认领 QUEUED Generation → 提交 gpt-image-2 → 轮询 → 归档 ResultAsset。

失败时用 n5_simplify_prompt 精简 prompt 重试一次；超时标 submit_unknown。
"""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import Batch, Generation, ResultAsset
from ..providers import APIMartClient, DeepSeekClient, ProviderError
from ..prompts import n5_simplify_prompt, retranslate_final_prompt, retranslate_final_user
from ..storage import get_storage

log = logging.getLogger("aetherforge.generation_worker")

ACTIVE_STATUSES = {"preparing", "submitting", "submitted", "processing", "archiving"}
CLAIM_BATCH_SIZE = 8

_NORMALIZED = {
    "pending": "processing",
    "processing": "processing",
    "in_progress": "processing",
    "submitted": "processing",
    "queued": "processing",
    "completed": "completed",
    "succeeded": "completed",
    "success": "completed",
    "failed": "failed",
    "error": "failed",
    "canceled": "failed",
    "cancelled": "failed",
}


def _prompt_json_client():
    return DeepSeekClient() if settings.deepseek_enabled else APIMartClient()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_status(state: dict) -> str:
    status = str(state.get("status") or "").lower()
    return _NORMALIZED.get(status, "processing")


def _looks_like_image(url: str) -> bool:
    clean = url.split("?")[0].lower()
    return clean.endswith((".png", ".jpg", ".jpeg", ".webp"))


def _extract_image_url(state) -> str:
    candidates: list[str] = []

    def walk(obj):
        if isinstance(obj, str):
            if obj.startswith("http") and _looks_like_image(obj) and obj not in candidates:
                candidates.append(obj)
        elif isinstance(obj, dict):
            for key, value in obj.items():
                if (
                    isinstance(key, str)
                    and isinstance(value, str)
                    and value.startswith("http")
                    and any(token in key.lower() for token in ("image", "url", "output", "result"))
                ):
                    candidates.append(value)
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(state)
    return candidates[0] if candidates else ""


def _percent(value) -> str:
    try:
        number = max(0, min(1, float(value)))
    except (TypeError, ValueError):
        number = 0
    return f"{round(number * 100):g}%"


def _annotation_line(annotation: dict, index: int) -> str:
    note = str(annotation.get("note") or "").strip()
    kind = str(annotation.get("kind") or "area").strip() or "area"
    rect = annotation.get("rect")
    if isinstance(rect, list) and len(rect) >= 4:
        area = (
            f"x={_percent(rect[0])}, y={_percent(rect[1])}, "
            f"width={_percent(rect[2])}, height={_percent(rect[3])}"
        )
    else:
        area = "marked area"
    suffix = f" - requested change: {note}" if note else ""
    return f"{index}. {kind} at {area}{suffix}"


def _revision_prompt_text(base_prompt: str, feedback: dict | None) -> str:
    if not isinstance(feedback, dict):
        return base_prompt
    description = str(feedback.get("description") or "").strip()
    annotations = [
        item for item in feedback.get("annotations") or []
        if isinstance(item, dict)
    ]
    lines = ["Edit the provided image according to the user's request."]
    if description:
        lines.append(description)
    if annotations:
        lines.append("Marked areas:")
        lines.extend(_annotation_line(item, index) for index, item in enumerate(annotations, start=1))
    return "\n".join(lines)


def _prompt_for_submission(gen: Generation) -> str:
    return _revision_prompt_text(gen.prompt_text, (gen.rule_snapshot or {}).get("revision_feedback"))


def _submit(db: Session, gen: Generation, client: APIMartClient) -> str | None:
    try:
        image_urls: list[str] = []
        for path in gen.reference_snapshot or []:
            try:
                with get_storage().local_path(path) as local:
                    image_urls.append(client.to_image_url(str(local)))
            except Exception:
                continue
        prompt_text = _prompt_for_submission(gen)
        gen.provider_payload = {
            "image_urls": image_urls,
            "size": gen.size,
            "resolution": gen.resolution,
        }
        db.flush()
        task_id = client.submit_generation(prompt_text, image_urls, gen.size, gen.resolution)
        gen.provider_task_id = task_id
        gen.status = "submitted"
        gen.submitted_at = _now()
        gen.failure_reason = ""
        db.flush()
        return task_id
    except ProviderError as exc:
        gen.failure_reason = str(exc)
        return None


def _poll_task(client: APIMartClient, task_id: str) -> dict:
    deadline = time.monotonic() + settings.generation_poll_interval_seconds * settings.generation_max_polls
    while time.monotonic() < deadline:
        try:
            state = client.get_task(task_id)
        except ProviderError as exc:
            log.warning("poll task %s failed: %s", task_id, exc)
            time.sleep(settings.generation_poll_interval_seconds)
            continue
        status = _normalize_status(state)
        if status == "completed":
            return {"timeout": False, "failed": False, "url": _extract_image_url(state), "reason": ""}
        if status == "failed":
            return {"timeout": False, "failed": True, "url": "", "reason": str(state.get("error") or state.get("message") or "生图失败")}
        time.sleep(settings.generation_poll_interval_seconds)
    return {"timeout": True, "failed": False, "url": "", "reason": "轮询超时"}


def _simplify_prompt(db: Session, gen: Generation) -> bool:
    try:
        result = _prompt_json_client().complete_json(
            n5_simplify_prompt(),
            gen.prompt_text,
            reasoning_effort="low",
            max_tokens=4096,
        )
        node = result["json"]
        english = str(node.get("english_prompt") or "").strip()
        if english:
            gen.prompt_text = english
    except (ProviderError, ValueError, KeyError) as exc:
        log.warning("simplify prompt failed: %s", exc)
        gen.failure_reason = f"精简提示词失败：{exc}"
        return False
    snapshot = dict(gen.rule_snapshot or {})
    snapshot["simplify_retried"] = True
    gen.rule_snapshot = snapshot
    db.flush()
    return True


def _retranslate(db: Session, gen: Generation) -> bool:
    """用户改过中文生图提示词：按最新中文重译出最终英文 final，覆盖本次提交用，不落库。"""
    snapshot = gen.rule_snapshot or {}
    try:
        result = _prompt_json_client().complete_json(
            retranslate_final_prompt(snapshot.get("site") or ""),
            retranslate_final_user(
                str(snapshot.get("zh") or ""),
                str(snapshot.get("identity_lock") or ""),
                list(snapshot.get("facts") or []),
                snapshot.get("site") or "",
                str(snapshot.get("target_language_copy") or ""),
            ),
            reasoning_effort="low",
            max_tokens=4096,
            thinking=False,
        )
        node = result["json"]
        english = str(node.get("final") or "").strip() if isinstance(node, dict) else ""
        if not english:
            gen.failure_reason = "中文提示词翻译返回为空"
            return False
        gen.prompt_text = english
    except (ProviderError, ValueError, KeyError) as exc:
        log.warning("retranslate zh prompt failed: %s", exc)
        gen.failure_reason = f"中文提示词翻译失败：{exc}"
        return False
    return True


def _finalize_completed(db: Session, gen: Generation, url: str, client: APIMartClient) -> None:
    try:
        data = client.download(url)
    except ProviderError as exc:
        gen.status = "failed"
        gen.failure_reason = f"下载结果失败：{exc}"
        return
    if not data:
        gen.status = "failed"
        gen.failure_reason = "生图结果为空"
        return
    suffix = Path(url.split("?")[0]).suffix or ".png"
    result_path = (
        f"results/{gen.batch_id}/{gen.cluster_id}/{gen.output_slot_id}/{gen.attempt}/{uuid.uuid4().hex}{suffix}"
    )
    try:
        get_storage().save(result_path, data)
    except OSError:
        gen.status = "failed"
        gen.failure_reason = "结果归档失败"
        return
    db.add(
        ResultAsset(
            generation_id=gen.id,
            storage_path=result_path,
            source_url=url,
            sha256=hashlib.sha256(data).hexdigest(),
            file_size=len(data),
        )
    )
    gen.status = "completed"
    gen.completed_at = _now()
    _refresh_batch_status(db, gen.batch_id)


def _refresh_batch_status(db: Session, batch_id) -> None:
    batch = db.get(Batch, batch_id)
    if batch is not None:
        batch.recompute_status()


def _attempt(db: Session, gen: Generation, client: APIMartClient) -> None:
    for attempt in range(2):
        if attempt == 1:
            if gen.rule_snapshot.get("simplify_retried"):
                break
            if not _simplify_prompt(db, gen):
                gen.status = "failed"
                return
        # 三节点管线下提示词直接就是最终英文；旧版 zh 数据不能直发 gpt-image-2，提示重新预备
        if gen.rule_snapshot.get("prompt_lang") == "zh":
            gen.status = "failed"
            gen.failure_reason = "提示词已过期（旧版中文），请重新预备生成"
            return
        # 用户改过中文生图提示词 → 生成时重译成无歧义英文 final（当地语文案逐字保留），仅本次提交用、不落库
        if gen.rule_snapshot.get("zh_edited"):
            if not _retranslate(db, gen):
                gen.status = "failed"
                return
        task_id = _submit(db, gen, client)
        if task_id is None:
            gen.status = "failed"
            return
        outcome = _poll_task(client, task_id)
        if outcome["timeout"]:
            gen.status = "submit_unknown"
            gen.failure_reason = outcome["reason"]
            return
        if not outcome["failed"]:
            _finalize_completed(db, gen, outcome["url"], client)
            return
        gen.failure_reason = outcome["reason"]
    gen.status = "failed"


def _process(generation_id: str) -> None:
    with SessionLocal() as db:
        gen = db.get(Generation, generation_id)
        if gen is None or gen.status != "submitting":
            return
        try:
            _attempt(db, gen, APIMartClient())
        except Exception as exc:
            db.rollback()
            gen = db.get(Generation, generation_id)
            if gen is not None and gen.status not in {"canceled"}:
                gen.status = "failed"
                gen.failure_reason = f"出图异常：{exc}"
        db.commit()


def _active_count(db: Session) -> int:
    return db.query(Generation).filter(Generation.status.in_(ACTIVE_STATUSES)).count()


def _claim_queued(db: Session, limit: int) -> list[str]:
    generations = (
        db.query(Generation)
        .filter_by(status="queued")
        .order_by(Generation.created_at.desc(), Generation.id.desc())
        .limit(min(limit, CLAIM_BATCH_SIZE))
        .all()
    )
    claimed = [str(g.id) for g in generations]
    for generation in generations:
        generation.status = "submitting"
    if claimed:
        db.commit()
    return claimed


def _recover_orphaned_submitting(db: Session) -> int:
    generations = (
        db.query(Generation)
        .filter_by(status="submitting")
        .filter(Generation.provider_task_id.is_(None))
        .all()
    )
    for generation in generations:
        generation.status = "queued"
    if generations:
        db.flush()
    return len(generations)


def _main_loop() -> None:
    while True:
        try:
            with SessionLocal() as db:
                active = _active_count(db)
                limit = max(0, settings.max_active_generations - active)
                claimed = _claim_queued(db, limit) if limit else []
            if claimed:
                workers = min(settings.max_active_generations, len(claimed))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    list(pool.map(_process, claimed))
                continue
        except Exception:
            log.exception("generation worker iteration failed")
        time.sleep(1.0)


def run() -> None:
    from ..db import wait_for_tables

    wait_for_tables()
    with SessionLocal() as db:
        recovered = _recover_orphaned_submitting(db)
        if recovered:
            db.commit()
            log.warning("recovered %s orphaned submitting generations", recovered)
    log.info("generation-worker started")
    _main_loop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    run()
