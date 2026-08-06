"""Deterministic check for the N2 split-slot prompt writer.

No network calls: a fake DeepSeek client proves the service calls one style
brief request plus one low-effort request per slot and normalizes the result.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.services.prepare as prepare_module
from backend.services.prepare import _generate_n_prompts_parallel, _n_prompts
from backend.services.prepare import _prompt_item


class FakeDeepSeek:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete_json(self, system: str, user: str, **kwargs):
        self.calls.append({"system": system, "user": user, "kwargs": kwargs})
        if user.startswith("请输出 style_brief"):
            return {"json": {"style_brief": "统一奶油白摄影风格"}}
        slot = int(user.split("slot_order=")[1].splitlines()[0])
        return {
            "json": {
                "slot": slot,
                "zh": f"槽位 {slot} 中文策划",
                "final": f"Slot {slot} final prompt. The reference product has exactly one body.",
                "target_language_copy": f"文案 {slot}",
            }
        }


def main() -> None:
    test_parallel_slot_generation()
    test_parallel_failure_falls_back_to_single_call()
    test_prompt_item_front_loads_shopee_ad_style_and_visible_copy()
    print("PASS: split-slot N2 prompt writer")


def test_parallel_slot_generation() -> None:
    slots = [
        {"order": 1, "name": "Shopee high-CTR main poster"},
        {"order": 2, "name": "Key benefit"},
        {"order": 3, "name": "Detail close-up"},
    ]
    client = FakeDeepSeek()
    style_brief, prompts = _generate_n_prompts_parallel(
        client,
        product_name="智能电饭煲",
        identity_lock="主商品 智能电饭煲：部件、数量、颜色、布局与参考图一致。",
        facts=["3.5L 大容量"],
        site="TH",
        person_policy="日常使用类，可出现真实家庭人物",
        slots=slots,
    )

    assert style_brief == "统一奶油白摄影风格"
    assert sorted(prompts) == [1, 2, 3]
    assert prompts[2]["zh"] == "槽位 2 中文策划"
    assert prompts[3]["target_language_copy"] == "文案 3"
    assert len(client.calls) == 4, client.calls
    slot_calls = client.calls[1:]
    assert all(call["kwargs"]["reasoning_effort"] == "low" for call in slot_calls)
    assert all(call["kwargs"]["thinking"] is True for call in slot_calls)


def test_parallel_failure_falls_back_to_single_call() -> None:
    class FallbackClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def complete_json(self, system: str, user: str, **kwargs):
            self.calls.append(system)
            if "请先为这款商品的一整套" in system:
                raise RuntimeError("parallel style failed")
            return {
                "json": {
                    "style_brief": "旧路径统一风格",
                    "prompts": [
                        {
                            "slot": 1,
                            "zh": "旧路径中文策划",
                            "final": "Fallback final prompt. The reference product has exactly one body.",
                            "target_language_copy": "旧路径文案",
                        }
                    ],
                }
            }

    fake_client = FallbackClient()
    original_client = prepare_module.DeepSeekClient
    prepare_module.DeepSeekClient = lambda: fake_client
    try:
        slot = SimpleNamespace(order=1, name="Shopee high-CTR main poster", id="slot-1")
        cluster = SimpleNamespace(
            name="智能电饭煲",
            product_name="智能电饭煲",
            identity_lock="主商品 智能电饭煲：部件、数量、颜色、布局与参考图一致。",
            product_facts="3.5L 大容量",
            analysis_snapshot={},
            batch=SimpleNamespace(output_template=SimpleNamespace(slots=[slot]), global_prompt=""),
        )
        style_brief, prompts = _n_prompts(None, cluster, "TH")
    finally:
        prepare_module.DeepSeekClient = original_client

    assert style_brief == "旧路径统一风格"
    assert prompts[1]["zh"] == "旧路径中文策划"
    assert len(fake_client.calls) == 2


def test_prompt_item_front_loads_shopee_ad_style_and_visible_copy() -> None:
    parsed = _prompt_item({
        "slot": 1,
        "zh": "Shopee 主图：红黄撞色，大标题，促销角标。",
        "target_language_copy": "HOT SALE\nส่งฟรี",
        "final": (
            "IDENTITY: The reference product has exactly one rice cooker. "
            "TEXT RENDERING: Embed the Thai copy exactly as provided in the target_language_copy field."
        ),
    })
    assert parsed is not None
    _, prompt = parsed
    assert prompt["final"].startswith("Create a high-CTR Shopee Southeast Asia marketplace advertising poster")
    assert "target_language_copy field" not in prompt["final"]
    assert "HOT SALE" in prompt["final"]
    assert "ส่งฟรี" in prompt["final"]


if __name__ == "__main__":
    main()
