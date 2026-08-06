"""离线验证 prepare 管线：mock DeepSeek/APIMart，跑 N1–N7 → READY + 8 PromptVersion。"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from backend.db import SessionLocal
from backend.models import Batch, Cluster, PromptVersion, User
from backend.services.assets import register_uploaded_asset
from backend.services.prepare import run_cluster_preparation


def _fake_deepseek(self, system, user, **kwargs):
    import json

    if "购买决策任务" in user:
        plans = [
            {
                "slot": i,
                "task": t,
                "goal": f"目标{i}",
                "layout": f"构图{i}",
                "person_policy": "without_person",
                "person_description": "",
                "localization": "泰式风格",
                "copy": f"文案{i}",
                "emphasis": f"强调{i}",
            }
            for i, t in enumerate(
                ["first_glance_value", "core_benefit", "proof", "usage", "detail_trust", "scene_closing", "spec_table"], 1
            )
        ]
        return {"json": {"design_list": plans}, "raw_text": ""}
    return {
        "json": {
            "target_language_copy": {"language": "Thai", "lines": ["ป้ายโฆษณา"]},
            "english_prompt": "1. IDENTITY: The reference product has exactly 1 component.\n4. TEXT RENDERING: Render: ป้ายโฆษณา\n5. EMPHASIS",
        },
        "raw_text": "",
    }


def main():
    from backend import providers
    from backend.prompts import n4_system, n4_user, n5_system, n5_user
    from backend.services import prepare as prepare_mod

    providers.DeepSeekClient.complete_json = _fake_deepseek

    # 视觉补齐 mock：无 APIMART key 时 prepare 直接降级，这里不 mock（走 except 分支）
    db = SessionLocal()
    u = db.query(User).first()
    batch = Batch(owner_id=u.id, name="prep-test", status="draft")
    db.add(batch)
    db.flush()

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 20, 30)).save(buf, format="PNG")
    asset = register_uploaded_asset(db, batch, "cup.png", buf.getvalue(), "image/png", "organize", u.id)
    db.commit()

    cluster = db.query(Cluster).filter_by(batch_id=batch.id).first()
    cluster.product_name = "智慧保温杯"
    cluster.product_facts = "容量500ml\n材质316不锈钢"
    db.commit()

    from backend.services.assets import request_cluster_preparation

    request_cluster_preparation(db, cluster, auto_generate=False)
    db.commit()

    ok = run_cluster_preparation(db, cluster, u.id)
    db.commit()
    print("prepare ok:", ok)
    print("status:", cluster.preparation_status, "stage:", cluster.preparation_stage)
    print("error:", cluster.preparation_error)

    pvs = db.query(PromptVersion).filter_by(cluster_id=cluster.id).all()
    print("PromptVersion count:", len(pvs))
    for pv in sorted(pvs, key=lambda p: p.output_slot.order):
        print(f"  slot {pv.output_slot.order}: {pv.node_name} len={len(pv.prompt_text)}")

    assert ok, cluster.preparation_error
    assert cluster.preparation_status == "ready"
    assert len(pvs) == 8, len(pvs)
    assert (cluster.analysis_snapshot or {}).get("_runtime_contract_fingerprint")
    print("\nPREPARE PIPELINE OK")

    db.close()


if __name__ == "__main__":
    sys.exit(main())
