"""DB 级集成测试：persist_prompts_direct 在真实 9 槽模板上写双语 PromptVersion。

确定性路径（不调模型）：建 throwaway Batch+Cluster → persist_prompts_direct 写入
{slot: {final, zh, target_language_copy}} → 断言 9 条、lang=en、display_prompt=zh、node_name=prompt_writer、
槽位覆盖 1-9 → 清理。

在服务器容器内运行：docker exec aetherforge-prompt-worker python -m scripts.test_persist_direct
"""
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT if (ROOT / "backend").is_dir() else Path("/app")))

from backend.db import SessionLocal, init_db
from backend.models import Batch, Cluster, User
from backend.seed import seed_output_template
from backend.services.template import global_fallback_template, template_slots
from backend.services.prompt_compile import edit_prompt_text, persist_prompts_direct

SLOT_NAMES = {1: "Shopee high-CTR main poster", 9: "Quality and trust"}


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        seed_output_template(db)
        db.flush()

        user = db.query(User).filter_by(role="admin").order_by(User.created_at).first()
        assert user is not None, "无 admin 用户"

        template = global_fallback_template(db)
        assert template is not None, "无全局兜底模板"
        slots = [s for s in template_slots(template) if s.name != "Seller original product photo"]
        assert len(slots) == 9, f"模板槽数应为 9，实际 {len(slots)}：{[s.name for s in slots]}"

        batch = Batch(
            owner_id=user.id,
            name=f"__integ_test_{uuid.uuid4().hex[:8]}",
            platform="shopee",
            site="TH",
            market="TH",
            output_template_id=template.id,
            ai_recognition_enabled=False,
        )
        db.add(batch)
        db.flush()

        cluster = Cluster(
            batch_id=batch.id,
            name="集成测试电饭煲",
            sku="IT-INTEG-001",
            product_name="智能电饭煲",
            product_facts="3.5L 大容量\n24 小时智能预约",
            identity_lock="主商品 智能电饭煲，部件/数量/颜色/布局与参考图一致，禁止增减部件。",
            relation_type="single_product",
        )
        db.add(cluster)
        db.flush()

        prompts = {
            order: {
                "final": (
                    f"Create a polished 1:1 Shopee listing image for slot {order}. "
                    f"The reference product has exactly one main body, one liner and one lid; "
                    f'colors match the reference image. Show exact visible text: "พร้อมใช้" (slot {order}).'
                ),
                "zh": f"槽位 {order} 中文生图提示词：保持奶白机身，呈现真实使用场景。",
                "target_language_copy": f"พร้อมใช้ slot {order}",
            }
            for order in range(1, 10)
        }
        style_brief = "统一奶油白柔和影棚光，浅灰渐变背景，产品居中偏下微俯拍。"
        created = persist_prompts_direct(db, cluster, prompts, style_brief, actor_id=user.id)
        db.flush()

        assert len(created) == 9, f"应写 9 条 PromptVersion，实际 {len(created)}"
        langs = {pv.structured_output.get("lang") for pv in created}
        assert langs == {"en"}, f"lang 应全为 en：{langs}"
        by_order = {pv.output_slot.order: pv for pv in created}
        assert set(by_order) == set(range(1, 10)), f"槽位应覆盖 1-9：{sorted(by_order)}"
        for order, pv in sorted(by_order.items()):
            assert pv.prompt_text.strip(), f"槽位 {order} prompt 为空"
            assert pv.node_name == "prompt_writer", f"槽位 {order} node_name={pv.node_name}"
            display_prompt = pv.structured_output.get("node_output", {}).get("display_prompt") or ""
            assert display_prompt.startswith(prompts[order]["zh"]), f"槽位 {order} display_prompt 应保留中文生图提示词"
            assert "画面可见文字：" in display_prompt, f"槽位 {order} 中文生图提示词应包含可见文字段"
            assert prompts[order]["target_language_copy"] in display_prompt, f"槽位 {order} 中文稿应包含当地语言文案"
            assert pv.structured_output.get("target_language_copy") == prompts[order]["target_language_copy"]
            assert pv.output_slot.name == SLOT_NAMES.get(order, pv.output_slot.name)

        edited = edit_prompt_text(
            db,
            cluster,
            1,
            by_order[1].prompt_text,
            display_prompt=(
                "主图中文生图提示词：突出完整商品和核心卖点。\n"
                "画面可见文字：\n"
                "ข้อความใหม่\n"
                "จุดขายใหม่"
            ),
            actor_id=user.id,
        )
        edited_structured = edited.structured_output or {}
        assert edited_structured.get("target_language_copy") == "ข้อความใหม่\nจุดขายใหม่"
        assert edited_structured.get("visible_text_lines") == ["ข้อความใหม่", "จุดขายใหม่"]

        print("PASS：9 条双语 PromptVersion")
        print(f"  模板槽数：{len(slots)}")
        print(f"  槽名：{', '.join(s.name for s in slots)}")
        print(f"  槽位覆盖：{sorted(by_order)}；lang=en；display_prompt=zh；node_name=prompt_writer")

        db.delete(cluster)
        db.flush()
        db.delete(batch)
        db.commit()
        print("清理完成：throwaway batch/cluster 已删除")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
