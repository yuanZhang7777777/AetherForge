"""真实 DeepSeek 验证新 N5：产出 7 张 concept/mood/typography 创意设计。"""
import sys
import json

sys.path.insert(0, r"e:\Project\AetherForge")

from backend.prompts import n4_system, n4_user, n4_person_policy
from backend.providers import DeepSeekClient

site = "TH"
product_name = "智能电饭煲"
identity_lock = "主商品 智能电饭煲，一个机身 + 一个内胆 + 一个可开合锅盖，颜色奶白，参考图一致，禁止增减部件。"
facts = [
    "3.5L 大容量，一次可煮 6 人份米饭",
    "底部 360° 环绕加热，米饭受热均匀不夹生",
    "内胆麦饭石不粘涂层，煮粥不糊底",
    "24 小时智能预约，早晨起床即食",
    "一键开盖防烫设计",
]
person_policy = n4_person_policy({"category": "厨房电器", "name": "智能电饭煲"}, facts)
print("person_policy:", person_policy)

print("=" * 60)
print("SYSTEM 前 400 字：")
print(n4_system(site)[:400])
print("=" * 60)

from backend.config import settings

client = DeepSeekClient()
result = client.complete_json(
    n4_system(site),
    n4_user(product_name, identity_lock, facts, site, person_policy, []),
    reasoning_effort="high",
    max_tokens=16384,
    thinking=False,
    temperature=settings.deepseek_temperature,
)
node = result["json"]
design_list = node.get("design_list") if isinstance(node, dict) else None
print(f"design_list 张数：{len(design_list) if isinstance(design_list, list) else 'N/A'}")
print("style_brief:", node.get("style_brief") if isinstance(node, dict) else "N/A")
if isinstance(design_list, list):
    for i, d in enumerate(design_list, 1):
        print(f"\n--- 第 {i} 张 slot={d.get('slot')} task={d.get('task')} ---")
        print("concept:", d.get("concept"))
        print("mood:", d.get("mood"))
        print("layout:", d.get("layout"))
        print("typography:", d.get("typography"))
        print("copy:", repr(d.get("copy")))
