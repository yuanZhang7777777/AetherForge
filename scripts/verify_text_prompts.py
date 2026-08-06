"""服务器文本链路验证：用真实 DeepSeek key 跑 N2/N4/N5，打印提示词输出。

输入是模拟 N1 的假逐图证据（不必等真实商品图），重点看：
- N2 是否生成合格身份锁
- N4 是否产出 6-8 张递进设计稿、站点文案语言是否正确
- N5 是否编译出五段式英文 Prompt、泰文原样嵌入
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import prompts  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.pipeline import SOCIAL_PROOF_WORDS, SPEC_TABLE_WORDS  # noqa: E402
from backend.providers import DeepSeekClient  # noqa: E402

SITE = "TH"
PRODUCT_NAME = "无线蓝牙耳机 Pro"
POINTS = [
    "蓝牙5.4连接",
    "主动降噪ANC -40dB",
    "续航40小时",
    "Hi-Res认证音质",
    "记忆海绵耳罩佩戴舒适",
    "快充10分钟听4小时",
    "累计销量10万+",
    "产品尺寸：22x18x8cm，重量250g",
]

# 模拟 N1 视觉证据（假设模型已识别）
FAKE_EVIDENCE = [
    {
        "index": 0,
        "image_role": "main_product",
        "contains_target": True,
        "reference_quality": 92,
        "observed_identity": (
            "黑色头戴式无线蓝牙耳机，左耳罩外壳有品牌Logo，耳罩可旋转折叠，"
            "两侧各3个实体按键（音量+/音量-/电源），右耳罩底部USB-C充电口。"
        ),
        "recommended_use": "semantic_extract_source",
    },
    {
        "index": 1,
        "image_role": "detail",
        "contains_target": True,
        "reference_quality": 85,
        "observed_identity": "同一耳机背面视角，头梁内侧有软垫，头梁可伸缩调节，两侧共6档刻度。",
        "recommended_use": "evidence_only",
    },
    {
        "index": 2,
        "image_role": "packaging",
        "contains_target": True,
        "reference_quality": 60,
        "observed_identity": "包装盒内含耳机、USB-C充电线、3.5mm音频线、收纳袋。",
        "recommended_use": "evidence_only",
    },
]


def main() -> None:
    print("=== 环境 ===")
    print(f"deepseek_api_key: {'已配置' if settings.deepseek_api_key else 'MISSING'}")
    print(f"model: {settings.deepseek_prompt_model}")
    print(f"offline_mode: {settings.offline_mode}")
    if not settings.deepseek_api_key or settings.offline_mode:
        print("!! 未配置 key 或处于离线模式，中止。")
        sys.exit(1)
    ds = DeepSeekClient()
    print()

    # ---------- N2 ----------
    print("############ N2 多图汇总与主商品判定 ############")
    out2 = ds.complete_json(
        system=prompts.n2_system(),
        user=prompts.n2_user(PRODUCT_NAME, POINTS, SITE, FAKE_EVIDENCE),
        reasoning_effort=settings.reasoning_effort_deep,
        max_tokens=settings.max_tokens_deep,
    )
    decision = out2["json"]
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    print()

    identity_lock = decision.get("identity_lock") or ""
    if decision.get("decision") != "continue":
        print(f"!! decision={decision.get('decision')}，未继续。原因：{decision.get('needs_input_reason')}")
        sys.exit(0)

    # ---------- N4 ----------
    print("############ N4 Shopee 详情页设计 ############")
    person_policy = prompts.n4_person_policy(decision.get("product_profile") or {}, POINTS)
    extra = [
        task
        for task, words in (("social_proof", SOCIAL_PROOF_WORDS), ("spec_table", SPEC_TABLE_WORDS))
        if any(w in "".join(POINTS) for w in words)
    ]
    out4 = ds.complete_json(
        system=prompts.n4_system(SITE),
        user=prompts.n4_user(PRODUCT_NAME, identity_lock, POINTS, SITE, person_policy, extra),
        reasoning_effort=settings.reasoning_effort_deep,
        max_tokens=settings.max_tokens_deep,
    )
    parsed4 = out4["json"]
    design_list = parsed4.get("design_list") if isinstance(parsed4, dict) else parsed4
    print(f"person_policy: {person_policy}")
    print(f"extra_tasks: {extra}")
    print(f"design count: {len(design_list)}")
    for d in design_list:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        print("---")
    print()

    # ---------- N5（前 2 张） ----------
    print("############ N5 逐张编译（前 2 张） ############")
    for slot in design_list[:2]:
        out5 = ds.complete_json(
            system=prompts.n5_system(SITE),
            user=prompts.n5_user(PRODUCT_NAME, identity_lock, POINTS, SITE, slot),
            reasoning_effort=settings.reasoning_effort_compile,
            max_tokens=settings.max_tokens_compile,
        )
        print(f"===== slot {slot.get('slot')} ({slot.get('task')}) =====")
        print(json.dumps(out5["json"], ensure_ascii=False, indent=2))
        print()


if __name__ == "__main__":
    main()
