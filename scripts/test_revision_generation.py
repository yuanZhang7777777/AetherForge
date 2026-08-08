"""Revision generation regression check.

修图请求必须：
1. 新建同槽位下一版 generation。
2. 把上一版结果图放到 reference_snapshot 第一位。
3. 保留原商品参考图。
4. worker 提交给 image2 的 prompt 包含全局修改说明、单个标记说明和区域坐标。
"""
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT if (ROOT / "backend").is_dir() else Path("/app")))

from backend.db import SessionLocal, init_db
from backend.models import Batch, Cluster, Generation, PromptVersion, ResultAsset, User
from backend.seed import seed_output_template
from backend.services.generation import revise_generation
from backend.services.template import global_fallback_template, template_slots
from backend.workers.generation_worker import _revision_prompt_text


def main() -> None:
    init_db()
    db = SessionLocal()
    marker = uuid.uuid4().hex[:8]
    batch_id = None
    try:
        seed_output_template(db)
        user = db.query(User).filter_by(role="admin").order_by(User.created_at).first()
        assert user is not None, "missing admin user"
        template = global_fallback_template(db)
        slot = template_slots(template)[0]

        batch = Batch(owner_id=user.id, name=f"__revision_test_{marker}", output_template_id=template.id)
        db.add(batch)
        db.flush()
        batch_id = batch.id
        cluster = Cluster(batch_id=batch.id, name=f"__revision_cluster_{marker}", product_name="测试商品")
        db.add(cluster)
        db.flush()
        prompt = PromptVersion(
            cluster_id=cluster.id,
            output_slot_id=slot.id,
            created_by_id=user.id,
            node_name="prompt_writer",
            prompt_text="Original ecommerce poster prompt.",
        )
        db.add(prompt)
        db.flush()
        source = Generation(
            batch_id=batch.id,
            cluster_id=cluster.id,
            output_slot_id=slot.id,
            prompt_version_id=prompt.id,
            created_by_id=user.id,
            attempt=1,
            status="completed",
            prompt_text=prompt.prompt_text,
            reference_snapshot=["assets/original-product.png"],
        )
        db.add(source)
        db.flush()
        db.add(
            ResultAsset(
                generation_id=source.id,
                storage_path="results/previous-main.png",
                sha256="0" * 64,
                file_size=123,
            )
        )
        db.flush()

        feedback = {
            "issue_tags": ["logo_text"],
            "description": "整体文字放大，保持商品不变",
            "annotations": [
                {
                    "kind": "rect",
                    "rect": [0.1, 0.2, 0.3, 0.4],
                    "color": "#e11d48",
                    "width": 2,
                    "note": "把这里的泰文改清晰",
                }
            ],
        }
        revision = revise_generation(db, source, user, feedback)

        assert revision.attempt == 2
        assert revision.reference_snapshot[0] == "results/previous-main.png"
        assert "assets/original-product.png" in revision.reference_snapshot
        assert revision.rule_snapshot["revision_feedback"]["description"] == "整体文字放大，保持商品不变"
        assert revision.rule_snapshot["revision_feedback"]["annotations"][0]["note"] == "把这里的泰文改清晰"

        prompt_text = _revision_prompt_text(revision.prompt_text, revision.rule_snapshot["revision_feedback"])
        assert "Use the first reference image as the previous generated result" in prompt_text
        assert "整体文字放大，保持商品不变" in prompt_text
        assert "把这里的泰文改清晰" in prompt_text
        assert "x=10%, y=20%, width=30%, height=40%" in prompt_text

        db.rollback()
        print("PASS: revision generation keeps previous result and composes edit prompt")
    finally:
        if batch_id is not None:
            db.query(Generation).filter_by(batch_id=batch_id).delete(synchronize_session=False)
            db.query(PromptVersion).filter_by(cluster_id=cluster.id).delete(synchronize_session=False)
            db.query(Cluster).filter_by(batch_id=batch_id).delete(synchronize_session=False)
            db.query(Batch).filter_by(id=batch_id).delete(synchronize_session=False)
        db.commit()
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
