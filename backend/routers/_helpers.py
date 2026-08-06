"""路由公共工具：把 URL/body 里的字符串 ID 转成 uuid.UUID（Uuid 列只接受 UUID 对象）。"""
from __future__ import annotations

import uuid

from fastapi import HTTPException

from ..ids import safe_uuid


def coerce_uuid(value, not_found_message: str = "资源不存在") -> uuid.UUID:
    parsed = safe_uuid(value)
    if parsed is None:
        raise HTTPException(404, not_found_message)
    return parsed
