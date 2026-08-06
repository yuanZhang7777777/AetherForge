"""真实 DeepSeek 验证三节点「写提示词」节点：一次调用产出 9 张 中文策划(zh) + 最终英文提示词(final) + 当地语文案。

断言：
1. prompts 长度 = 9，slot 覆盖 1–9。
2. 每张 slot 的 zh 与 final 都非空（双语双输出）。
3. 每张 final 都是完整英文，且包含身份锁硬约束（The reference product has exactly ...）。
4. style_brief 非空（整套统一风格）。
5. TH 站点至少 2 张 final 含泰文原文（逐字文案嵌入，不被翻译成英文）。
6. 尺寸/容量等硬事实被采纳（至少一张引用 3.5L 或麦饭石，zh 或 final 均可）。
7. 无「避免最高级」等自我词语限制（无词语限制原则）。
"""
import sys
import re

sys.path.insert(0, r"e:\Project\AetherForge")

from backend.prompts import n_prompts_system, n_prompts_user, n4_person_policy
from backend.providers import DeepSeekClient

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
    {"order": 1, "name": "Standard white-background product hero"},
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
result = client.complete_json(
    n_prompts_system(SITE),
    n_prompts_user(PRODUCT_NAME, IDENTITY_LOCK, FACTS, SITE, person_policy, SLOTS),
    reasoning_effort="high",
    max_tokens=49152,
    thinking=True,
)
node = result["json"]
assert isinstance(node, dict), f"返回不是 JSON 对象：{type(node)}"

style_brief = str(node.get("style_brief") or "").strip()
prompts = node.get("prompts")
assert isinstance(prompts, list), "缺少 prompts 数组"
assert len(prompts) == 9, f"prompts 应为 9 张，实际 {len(prompts)}"

by_slot = {int(item["slot"]): item for item in prompts if isinstance(item, dict) and item.get("slot")}
assert set(by_slot) == set(range(1, 10)), f"slot 应覆盖 1–9，实际 {sorted(by_slot)}"

finals = {slot: str(item.get("final") or item.get("prompt") or "").strip() for slot, item in by_slot.items()}
zhs = {slot: str(item.get("zh") or "").strip() for slot, item in by_slot.items()}

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

# 4. TH 站点：至少 2 张 final 含泰文原文；主图（白底，无文字）不得含文案
thai_hits = [slot for slot, text in finals.items() if re.search(r"[฀-๿]", text)]
assert len(thai_hits) >= 2, f"TH 站点泰文文案嵌入不足，仅 {thai_hits} 张含泰文"
assert 1 not in thai_hits, "主图（白底 hero）不应含任何文案文字"

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
