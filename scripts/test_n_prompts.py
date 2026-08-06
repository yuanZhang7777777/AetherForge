"""真实 DeepSeek 验证三节点「写提示词」节点：style brief + 分槽并行产出 9 张提示词。

断言：
1. prompts 长度 = 9，slot 覆盖 1–9。
2. 每张 slot 的 zh 与 final 都非空（双语双输出）。
3. 每张 final 都是完整英文，且包含身份锁硬约束（The reference product has exactly ...）。
4. style_brief 非空（整套统一风格）。
5. TH 站点至少 3 张 final 含泰文原文（逐字文案嵌入，不被翻译成英文，主图也允许营销文案）。
6. 尺寸/容量等硬事实被采纳（至少一张引用 3.5L 或麦饭石，zh 或 final 均可）。
7. 无「避免最高级」等自我词语限制（无词语限制原则）。
"""
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.prompts import n4_person_policy
from backend.providers import DeepSeekClient
from backend.services.prepare import _generate_n_prompts_parallel

SITE = "TH"
PRODUCT_NAME = "智能电饭煲"
IDENTITY_LOCK = (
    "主商品 智能电饭煲，一个机身 + 一个内胆 + 一个可开合锅盖，颜色奶白，参考图一致，禁止增减部件。"
)
FACTS = [
    "3.5L 大容量，一次可煮 6 人份米饭",
    "底部 360° 环绕加热，米饭受热均匀不夹生",
    "内胆麦饭石不粘涂层，煮粥不糊底",
    "24 小时智能预约，早晨起床即食",
    "一键开盖防烫设计",
]
SLOTS = [
    {"order": 1, "name": "Shopee high-CTR main poster"},
    {"order": 2, "name": "Key benefit"},
    {"order": 3, "name": "Detail close-up"},
    {"order": 4, "name": "Real-life use"},
    {"order": 5, "name": "Pain point solution"},
    {"order": 6, "name": "Size and material"},
    {"order": 7, "name": "Usage steps"},
    {"order": 8, "name": "Lifestyle"},
    {"order": 9, "name": "Quality and trust"},
]

person_policy = n4_person_policy({"category": "厨房电器", "name": PRODUCT_NAME}, FACTS)
print("person_policy:", person_policy)
print("=" * 60)

client = DeepSeekClient()
style_brief, prompt_map = _generate_n_prompts_parallel(
    client,
    product_name=PRODUCT_NAME,
    identity_lock=IDENTITY_LOCK,
    facts=FACTS,
    site=SITE,
    person_policy=person_policy,
    slots=SLOTS,
)
assert len(prompt_map) == 9, f"prompts 应为 9 张，实际 {len(prompt_map)}"
assert set(prompt_map) == set(range(1, 10)), f"slot 应覆盖 1–9，实际 {sorted(prompt_map)}"

finals = {slot: str(item.get("final") or "").strip() for slot, item in prompt_map.items()}
zhs = {slot: str(item.get("zh") or "").strip() for slot, item in prompt_map.items()}

# 1. style_brief 非空
assert style_brief, "style_brief 为空"

# 1b. 每槽 zh 与 final 都非空（双语双输出）
empty_zh = [slot for slot in range(1, 10) if not zhs[slot]]
empty_final = [slot for slot in range(1, 10) if not finals[slot]]
assert not empty_zh, f"以下槽位 zh（中文策划）为空：{empty_zh}"
assert not empty_final, f"以下槽位 final（最终英文）为空：{empty_final}"

# 2. 身份锁保真：每张 final 都复述不变量硬约束句
identity_hard_missing = [
    slot for slot, text in finals.items()
    if "reference product has exactly" not in text.lower()
]
assert not identity_hard_missing, f"以下槽位 final 缺少身份锁硬约束句：{identity_hard_missing}"

# 2b. 每张 final 都是英文提示词（中文占比应很低，出现的中文只可能是局部说明）
for slot, text in finals.items():
    chinese = re.findall(r"[㐀-鿿]", text)
    assert len(chinese) <= 12, f"槽位 {slot} 疑似不是英文提示词：{text[:120]}"

# 3. 无「避免」类自我词语限制
restriction_hits = []
for slot, text in finals.items():
    if re.search(r"avoid.*(highest|superlative)|不要.*最高级|do not use.*(first|superlative)", text, re.I):
        restriction_hits.append(slot)
assert not restriction_hits, f"以下槽位存在词语限制：{restriction_hits}"

# 4. TH 站点：至少 3 张 final 含泰文原文；Shopee 主图允许营销文案
thai_hits = [slot for slot, text in finals.items() if re.search(r"[฀-๿]", text)]
assert len(thai_hits) >= 3, f"TH 站点泰文文案嵌入不足，仅 {thai_hits} 张含泰文"

# 5. 尺寸/容量等硬事实被采纳：zh 或 final 任一引用 3.5L 或麦饭石
spec_references = [
    slot for slot in range(1, 10)
    if re.search(r"3\.5\s?L|麦饭石|non-?stick", f"{zhs[slot]} {finals[slot]}")
]
assert spec_references, "硬事实（3.5L 容量 / 麦饭石不粘）未被任何槽位引用"

print(f"style_brief：{style_brief}")
print(f"9 张全部为双语（zh+final）；final 全部为英文、含身份锁硬约束；slot={sorted(finals)}")
print(f"含泰文原文的槽位：{sorted(thai_hits)}（逐字嵌入，未被翻译）")
print(f"引用 3.5L/麦饭石事实的槽位：{sorted(spec_references)}")
print("=" * 60)
for slot in range(1, 10):
    print(f"\n--- slot {slot} ({SLOTS[slot - 1]['name']}) ---")
    print(f"zh（前 100 字）：{zhs[slot][:100]}")
    print(f"final（前 180 字）：{finals[slot][:180]}")
print("\nPASS")
