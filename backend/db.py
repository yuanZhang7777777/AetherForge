"""SQLAlchemy 2.0 基础设施：engine / session / Base / init_db。"""
from __future__ import annotations

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

_URL = settings.database_url


def _make_engine():
    kwargs: dict = {"pool_pre_ping": True}
    if _URL.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow
        kwargs["pool_pre_ping"] = True
    return create_engine(_URL, **kwargs)


engine = _make_engine()

if _URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _record) -> None:  # pragma: no cover
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """建表 + 种子（admin、默认 OutputTemplate/slots）。"""
    from . import models  # noqa: F401
    from .security import hash_password
    from .seed import seed_output_template

    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    db = SessionLocal()
    try:
        from .models import User

        if db.query(User).filter_by(username=settings.seed_admin_username).first() is None:
            db.add(
                User(
                    username=settings.seed_admin_username,
                    email=settings.seed_admin_email,
                    role="admin",
                    password_hash=hash_password(settings.seed_admin_password),
                    must_change_password=False,
                )
            )
        seed_output_template(db)
        db.commit()
    finally:
        db.close()


def _ensure_columns() -> None:
    """补齐历史库的轻量列变更；正式迁移系统还没引入，启动时只做幂等加列。"""
    columns = {column["name"] for column in inspect(engine).get_columns("clusters")}
    if "store_name" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE clusters ADD COLUMN store_name VARCHAR(120) DEFAULT '' NOT NULL"))


def wait_for_tables(timeout: float = 60.0) -> None:
    """worker 启动时等待 web 建表，避免查询早于 create_all 而报 relation does not exist。"""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1 FROM clusters LIMIT 1"))
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("timed out waiting for database tables")
