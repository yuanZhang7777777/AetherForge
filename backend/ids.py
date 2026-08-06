"""ID 工具：字符串/UUID 互转。Uuid 列只接受 uuid.UUID 对象，路由与服务统一走这里。"""
from __future__ import annotations

import uuid


def safe_uuid(value) -> uuid.UUID | None:
    """字符串 ID → uuid.UUID；非法返回 None（不抛异常）。"""
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None
