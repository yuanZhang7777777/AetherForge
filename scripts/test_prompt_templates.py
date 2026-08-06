"""Deterministic DB check for per-user prompt templates."""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.db import SessionLocal, init_db
from backend.models import User
from backend.services.prompt_templates import (
    delete_user_prompt_template,
    list_user_prompt_templates,
    save_user_prompt_template,
)
from backend.security import hash_password


def make_user(db, username: str) -> User:
    user = User(
        username=username,
        email=f"{username}@example.test",
        password_hash=hash_password("secret"),
        must_change_password=False,
    )
    db.add(user)
    db.flush()
    return user


def main() -> None:
    init_db()
    db = SessionLocal()
    marker = uuid.uuid4().hex[:8]
    try:
        left = make_user(db, f"tpl-left-{marker}")
        right = make_user(db, f"tpl-right-{marker}")

        first = save_user_prompt_template(db, left, "暖光家居", "暖色调，真实家庭使用场景")
        second = save_user_prompt_template(db, right, "暖光家居", "冷色调，科技感")
        updated = save_user_prompt_template(db, left, "暖光家居", "奶油白背景，暖光家居")
        db.flush()

        assert first.id == updated.id
        assert second.id != first.id
        left_templates = list_user_prompt_templates(db, left)
        right_templates = list_user_prompt_templates(db, right)
        assert [item.name for item in left_templates] == ["暖光家居"]
        assert [item.content for item in left_templates] == ["奶油白背景，暖光家居"]
        assert [item.content for item in right_templates] == ["冷色调，科技感"]

        assert delete_user_prompt_template(db, left, first.id) is True
        assert list_user_prompt_templates(db, left) == []
        assert list_user_prompt_templates(db, right)[0].id == second.id

        db.rollback()
        print("PASS: per-user prompt templates")
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
