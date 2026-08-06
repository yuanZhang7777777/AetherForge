"""N1–N5 链路编排：逐图证据 → 主商品判定(身份锁) → 标准图 → 详情设计 → 逐张编译生图。

设计要点（对照 Coze Shopee_Listing_V2）：
- 逐张生成（batch 并发 1），绝不一次性生成多张
- 身份锁从 N2 贯穿 N4/N5
- 失败走显式降级：先精简 Prompt 重试一次，仍失败标记 degraded，不静默兜底
- OFFLINE_MODE=1 时用本地样例跑通链路（无密钥可验证）
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import prompts
from .config import settings
from .providers import APIMartClient, DeepSeekClient, ProviderError

GENERATION_SIZE = "1:1"
GENERATION_RESOLUTION = "1K"
GENERATION_POLL_SECONDS = 3
GENERATION_TIMEOUT_SECONDS = 300
CONFIDENCE_GATE = 80
# 含这些词的卖点触发第 7 张口碑/第 8 张规格图
SOCIAL_PROOF_WORDS = ("销量", "评分", "复购", "口碑", "爆款", "热卖", "评价")
SPEC_TABLE_WORDS = ("规格", "参数", "尺寸", "容量", "功率", "材质", "重量")


@dataclass
class PipelineResult:
    status: str  # completed / needs_input / partial / error
    standard_product_image_url: str = ""
    result_image_urls: list[str] = field(default_factory=list)
    message: str = ""
    identity_lock: str = ""
    details: dict = field(default_factory=dict)


class Pipeline:
    def __init__(
        self,
        *,
        deepseek: DeepSeekClient | None = None,
        apimart: APIMartClient | None = None,
        offline: bool | None = None,
    ):
        self.deepseek = deepseek or DeepSeekClient()
        self.apimart = apimart or APIMartClient()
        self.offline = settings.offline_mode if offline is None else offline

    # ------------------------------------------------------------ 主入口
    def run(
        self,
        product_images: list[str | Path],
        product_name: str,
        points: list[str],
        site: str,
        *,
        save_dir: str | Path | None = None,
    ) -> PipelineResult:
        images = [str(p) for p in product_images]
        points = [p for p in (points or []) if str(p).strip()]
        site = (site or "SG").upper()

        if self.offline:
            return self._run_offline(images, product_name, points, site, save_dir)

        save_dir = Path(save_dir) if save_dir else None
        try:
            evidence = self._n1_evidence(images, product_name)
        except ProviderError as exc:
            return PipelineResult(status="error", message=f"N1 证据提取失败：{exc}", details={"stage": "n1"})

        try:
            decision = self._n2_decide(evidence, product_name, points, site)
        except ProviderError as exc:
            return PipelineResult(status="error", message=f"N2 主商品判定失败：{exc}", details={"stage": "n2"})

        if decision.get("decision") != "continue" or int(decision.get("confidence") or 0) < CONFIDENCE_GATE:
            return PipelineResult(
                status="needs_input",
                message=decision.get("needs_input_reason") or "主商品不明确，请补充更清晰的商品图或资料。",
                identity_lock=decision.get("identity_lock") or "",
                details={"stage": "n2", "decision": decision},
            )

        identity_lock = decision.get("identity_lock") or ""
        source_index = int(decision.get("source_image_index") or 0)
        supporting = [int(i) for i in (decision.get("supporting_image_indexes") or [])]

        try:
            standard_url = self._n3_standard(decision, images, source_index, save_dir=save_dir)
        except ProviderError as exc:
            return PipelineResult(status="error", message=f"N3 标准图生成失败：{exc}", details={"stage": "n3"})

        try:
            designs = self._n4_designs(decision, product_name, points, site)
        except ProviderError as exc:
            return PipelineResult(status="error", message=f"N4 详情设计失败：{exc}", details={"stage": "n4"})

        result_urls: list[str] = []
        degraded: list[int] = []
        references = [u for u in [standard_url] + [images[i] for i in supporting if i < len(images) and i != source_index] if u]
        for idx, design in enumerate(designs, start=1):
            url = self._n5_slot(design, product_name, identity_lock, points, site, references, save_dir, idx)
            if url:
                result_urls.append(url)
            else:
                degraded.append(idx)

        status = "completed" if not degraded else ("partial" if result_urls else "error")
        message = ""
        if degraded:
            done = [i for i in range(1, len(designs) + 1) if i not in degraded]
            message = f"第 {', '.join(map(str, degraded))} 张生成失败，已显式降级跳过。成功：{len(result_urls)} 张。"
            if not result_urls:
                message = "全部详情图生成失败。"

        return PipelineResult(
            status=status,
            standard_product_image_url=standard_url,
            result_image_urls=result_urls,
            message=message,
            identity_lock=identity_lock,
            details={
                "stage": "done",
                "evidence": evidence,
                "decision": decision,
                "designs": designs,
                "degraded_slots": degraded,
            },
        )

    # ------------------------------------------------------------ N1 逐图证据
    def _n1_evidence(self, images: list[str], product_name: str) -> list[dict]:
        evidence: list[dict] = []
        for idx, image in enumerate(images):
            text = self.apimart.observe_image(prompts.n1_observe_instruction(product_name, idx), [image])
            parsed = extract_json(text)
            if not isinstance(parsed, dict):
                raise ProviderError(f"图 {idx} 证据解析失败")
            evidence.append({**parsed, "index": idx, "source": image})
        return evidence

    # ------------------------------------------------------------ N2 汇总判定
    def _n2_decide(self, evidence: list[dict], product_name: str, points: list[str], site: str) -> dict:
        out = self.deepseek.complete_json(
            system=prompts.n2_system(),
            user=prompts.n2_user(product_name, points, site, evidence),
            reasoning_effort=settings.reasoning_effort_deep,
            max_tokens=settings.max_tokens_deep,
        )
        parsed = out["json"]
        if not isinstance(parsed, dict):
            raise ProviderError("N2 判定输出不是对象")
        return parsed

    # ------------------------------------------------------------ N3 标准图
    def _n3_standard(self, decision: dict, images: list[str], source_index: int, *, save_dir: Path | None) -> str:
        mode = decision.get("standardization_mode") or "reuse"
        source = images[source_index] if source_index < len(images) else (images[0] if images else "")
        if not source:
            raise ProviderError("无可用源图")
        if mode == "reuse":
            return source
        prompt = prompts.n3_standard_prompt(
            mode,
            decision.get("identity_lock") or "",
            decision.get("points") or [],
        )
        return self._generate(prompt, [source], f"{mode}_standard", save_dir, is_standard=True)

    # ------------------------------------------------------------ N4 详情设计
    def _n4_designs(self, decision: dict, product_name: str, points: list[str], site: str) -> list[dict]:
        person_policy = prompts.n4_person_policy(decision.get("product_profile") or {}, points)
        extra = [t for t, words in (("social_proof", SOCIAL_PROOF_WORDS), ("spec_table", SPEC_TABLE_WORDS)) if any(w in "".join(points) for w in words)]
        out = self.deepseek.complete_json(
            system=prompts.n4_system(site),
            user=prompts.n4_user(
                product_name,
                decision.get("identity_lock") or "",
                points,
                site,
                person_policy,
                extra,
            ),
            reasoning_effort=settings.reasoning_effort_deep,
            max_tokens=settings.max_tokens_deep,
        )
        parsed = out["json"]
        if isinstance(parsed, list):
            design_list = parsed
        elif isinstance(parsed, dict):
            design_list = parsed.get("design_list")
        else:
            design_list = None
        if not isinstance(design_list, list) or not design_list:
            raise ProviderError("N4 未返回有效设计稿数组")
        if not 6 <= len(design_list) <= 8:
            design_list = design_list[:8]  # 硬上限，防止越界
        return design_list

    # ------------------------------------------------------------ N5 逐张编译+生图
    def _n5_slot(
        self,
        design: dict,
        product_name: str,
        identity_lock: str,
        points: list[str],
        site: str,
        references: list[str],
        save_dir: Path | None,
        slot: int,
    ) -> str:
        compiled = self._compile(design, product_name, identity_lock, points, site)
        if not compiled:
            return ""
        prompt = compiled.get("english_prompt") or ""
        if not prompt:
            return ""
        url = self._generate_with_retry(prompt, references, f"detail_{slot}", save_dir)
        return url

    def _compile(self, design: dict, product_name: str, identity_lock: str, points: list[str], site: str) -> dict | None:
        try:
            out = self.deepseek.complete_json(
                system=prompts.n5_system(site),
                user=prompts.n5_user(product_name, identity_lock, points, site, design),
                reasoning_effort=settings.reasoning_effort_compile,
                max_tokens=settings.max_tokens_compile,
            )
            parsed = out["json"]
            return parsed if isinstance(parsed, dict) else None
        except ProviderError:
            return None

    def _generate_with_retry(self, prompt: str, references: list[str], name: str, save_dir: Path | None) -> str:
        try:
            return self._generate(prompt, references, name, save_dir)
        except ProviderError:
            simplified = self._simplify(prompt)
            if not simplified:
                return ""
            try:
                return self._generate(simplified, references, name, save_dir, retry=True)
            except ProviderError:
                return ""

    def _simplify(self, prompt: str) -> str:
        try:
            out = self.deepseek.complete_json(
                system="你是生图 Prompt 精简器。",
                user=prompts.n5_simplify_prompt() + "\n\n原 Prompt：\n" + prompt,
                reasoning_effort=settings.reasoning_effort_compile,
                max_tokens=settings.max_tokens_compile,
            )
            parsed = out["json"]
            return parsed.get("english_prompt") if isinstance(parsed, dict) else ""
        except ProviderError:
            return ""

    def _generate(
        self,
        prompt: str,
        references: list[str],
        name: str,
        save_dir: Path | None,
        *,
        is_standard: bool = False,
        retry: bool = False,
    ) -> str:
        ref_urls = [self.apimart.to_image_url(r) for r in references if r]
        task_id = self.apimart.submit_generation(
            prompt, ref_urls, GENERATION_SIZE, GENERATION_RESOLUTION
        )
        urls = self._wait_generation(task_id)
        url = urls[0]
        if save_dir:
            return self._save(url, save_dir, name, retry)
        return url

    def _wait_generation(self, task_id: str) -> list[str]:
        deadline = time.time() + GENERATION_TIMEOUT_SECONDS
        while time.time() < deadline:
            payload = self.apimart.get_task(task_id)
            status = str(payload.get("status") or "").lower()
            if status in {"completed", "succeeded", "success"}:
                urls = _image_urls(payload)
                if urls:
                    return urls
                return []
            if status in {"failed", "error", "canceled", "cancelled"}:
                detail = payload.get("error") or payload.get("message") or "provider failed"
                raise ProviderError(f"生图任务失败：{detail}")
            time.sleep(GENERATION_POLL_SECONDS)
        raise ProviderError("生图任务超时")

    def _save(self, url: str, save_dir: Path, name: str, retry: bool) -> str:
        save_dir.mkdir(parents=True, exist_ok=True)
        suffix = "_retry" if retry else ""
        target = save_dir / f"{name}{suffix}.png"
        target.write_bytes(self.apimart.download(url))
        return str(target)

    # ------------------------------------------------------------ OFFLINE 样例
    def _run_offline(
        self,
        images: list[str],
        product_name: str,
        points: list[str],
        site: str,
        save_dir: str | Path | None,
    ) -> PipelineResult:
        source = images[0] if images else ""
        evidence = [
            {
                "index": i,
                "image_role": "main_product" if i == 0 else "detail",
                "contains_target": True,
                "reference_quality": 90 - i * 5,
                "observed_identity": f"离线样例：图 {i} 可见 {product_name} 主体",
                "recommended_use": "semantic_extract_source" if i == 0 else "evidence_only",
            }
            for i in range(len(images))
        ]
        decision = {
            "decision": "continue",
            "confidence": 95,
            "product_profile": {"category": "样例品类", "name": product_name, "color": "主色", "key_features": ["样例特征"]},
            "identity_lock": f"身份锁(离线样例)：主商品 {product_name}，结构/部件数量/颜色与源图完全一致，禁止增减部件。",
            "source_image_index": 0,
            "supporting_image_indexes": [i for i in range(1, len(images))],
            "standardization_mode": "reuse",
            "needs_input_reason": "",
        }
        standard_url = source
        designs = [
            {
                "slot": i,
                "task": t,
                "goal": f"离线样例设计目标{i}",
                "layout": "主体居中，浅色背景",
                "person_policy": "without_person",
                "person_description": "",
                "localization": "本地化样例",
                "copy": f"{site} 语样例文案 {i}",
                "emphasis": "离线样例",
            }
            for i, t in enumerate(prompts.DECISION_TASKS, start=1)
        ]
        result_urls = [f"offline://detail_{i}.png" for i in range(1, len(designs) + 1)]
        return PipelineResult(
            status="completed",
            standard_product_image_url=standard_url,
            result_image_urls=result_urls,
            message="离线模式：未调用真实模型，样例链路跑通。",
            identity_lock=decision["identity_lock"],
            details={"stage": "done", "offline": True, "evidence": evidence, "decision": decision, "designs": designs},
        )


def _image_urls(payload: dict) -> list[str]:
    if isinstance(payload.get("image_urls"), list):
        urls: list[str] = []
        for item in payload["image_urls"]:
            if isinstance(item, dict):
                item = item.get("url")
            if item:
                urls.append(str(item))
        return urls
    urls = []
    for image in (payload.get("result") or {}).get("images", []) if isinstance(payload.get("result"), dict) else []:
        value = image.get("url")
        if isinstance(value, list):
            urls.extend(str(v) for v in value if v)
        elif value:
            urls.append(str(value))
    return urls
