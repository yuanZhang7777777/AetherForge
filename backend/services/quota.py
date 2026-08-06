"""日配额：DailyGenerationUsage 预留/检查。"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import DailyGenerationUsage, User


def _today() -> str:
    return date.today().isoformat()


def _usage(db: Session, scope: str, user_id=None) -> int:
    query = db.query(DailyGenerationUsage).filter_by(scope=scope, date=_today())
    if scope == "user":
        query = query.filter_by(user_id=user_id)
    item = query.first()
    return item.used if item else 0


def _upsert_usage(db: Session, *, scope: str, date: str, user_id, increment: int) -> None:
    """配额累加。Postgres 用 ON CONFLICT 防并发重复插入；SQLite 开发环境用 get-or-create。"""
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert

        stmt = dialect_insert(DailyGenerationUsage).values(
            id=uuid.uuid4(), scope=scope, date=date, user_id=user_id, used=increment
        )
        if scope == "org":
            stmt = stmt.on_conflict_do_update(
                index_elements=["date"],
                index_where=text("scope = 'org'"),
                set_={"used": DailyGenerationUsage.used + increment},
            )
        else:
            stmt = stmt.on_conflict_do_update(
                index_elements=["date", "user_id"],
                index_where=text("scope = 'user'"),
                set_={"used": DailyGenerationUsage.used + increment},
            )
        db.execute(stmt)
        return
    item = db.query(DailyGenerationUsage).filter_by(scope=scope, date=date, user_id=user_id).first()
    if item is None:
        item = DailyGenerationUsage(scope=scope, date=date, user_id=user_id, used=0)
        db.add(item)
    item.used += increment


def reserve_generation_usage(db: Session, user: User, count: int) -> None:
    if count <= 0:
        return
    today = _today()
    if settings.user_daily_generation_limit > 0:
        used = _usage(db, "user", user.id)
        if used + count > settings.user_daily_generation_limit:
            raise ValueError("user daily quota exceeded")
    _upsert_usage(db, scope="org", date=today, user_id=None, increment=count)
    _upsert_usage(db, scope="user", date=today, user_id=user.id, increment=count)


def daily_usage_remaining(db: Session, user: User) -> tuple[bool, bool]:
    """返回 (org_blocked, user_blocked)。"""
    org_blocked = False
    user_blocked = False
    if settings.user_daily_generation_limit > 0:
        used = _usage(db, "user", user.id)
        user_blocked = used >= settings.user_daily_generation_limit
    return org_blocked, user_blocked
