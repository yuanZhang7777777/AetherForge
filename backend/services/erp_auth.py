"""ERP 登录认证（照搬 picturesGenerate platform_app/services.py）。

POST ERP_LOGIN_URL {"username","password"} → {success, code, data:{accessToken}}；
认证成功后在本地 get_or_create 用户，首次登录自动建号。
"""
from __future__ import annotations

import requests
from sqlalchemy.orm import Session

from ..config import settings
from ..models import User


class ErpAuthError(Exception):
    pass


class CatalogError(Exception):
    pass


def _catalog_response_data(response, expected_type):
    try:
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise CatalogError("Catalog service is unavailable") from exc
    status = payload.get("status") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or ("code" in payload and payload["code"] not in (200, "200"))
        or (
            status is not None
            and status not in (True, 200, "200", "ok", "success")
        )
        or not isinstance(payload.get("data"), expected_type)
    ):
        raise CatalogError("Catalog service returned an invalid response")
    return payload["data"]


def _extract_token(data):
    token = data.get("accessToken") or data.get("token")
    if not isinstance(token, str) or not token.strip():
        raise ValueError("missing token")
    return token.strip()


class ErpAuthClient:
    def __init__(self, session=None, timeout=None):
        self.session = session or requests.Session()
        self.timeout = timeout or settings.catalog_timeout_seconds

    def login(self, username, password):
        if not settings.erp_login_url:
            raise ErpAuthError("ERP 登录未配置")
        try:
            response = self.session.post(
                settings.erp_login_url,
                json={"username": username, "password": password},
                timeout=self.timeout,
            )
            data = _catalog_response_data(response, dict)
            return _extract_token(data)
        except CatalogError as exc:
            msg = None
            try:
                payload = response.json()
                msg = payload.get("msg") if isinstance(payload, dict) else None
            except (requests.RequestException, ValueError):
                pass
            raise ErpAuthError(msg or "ERP 登录失败，请检查用户名或密码") from exc
        except (ValueError, requests.RequestException) as exc:
            raise ErpAuthError("ERP 登录失败，请检查用户名或密码") from exc


def authenticate_erp_user(db: Session, username: str, password: str, *, client=None) -> tuple[User, str]:
    """验证 ERP 凭据，成功则本地 get_or_create 用户并同步角色。返回 (user, token)。"""
    username = str(username or "").strip()
    password = str(password or "")
    if not username or not password:
        raise ErpAuthError("ERP 用户名或密码不正确")
    try:
        token = (client or ErpAuthClient()).login(username, password)
    except ErpAuthError:
        raise
    except Exception as exc:
        raise ErpAuthError("ERP 登录服务暂时不可用") from exc
    admin_names = {name.strip().lower() for name in settings.platform_admin_erp_users if name.strip()}
    role = "admin" if username.lower() in admin_names else "operator"
    user = db.query(User).filter_by(username=username).first()
    if user is None:
        user = User(
            username=username,
            email="",
            password_hash="!",
            role=role,
            daily_generation_limit=settings.user_daily_generation_limit,
            must_change_password=False,
            is_active=True,
        )
        db.add(user)
        db.flush()
    else:
        if user.role != role:
            user.role = role
        if user.must_change_password:
            user.must_change_password = False
        user.password_hash = "!"
    db.commit()
    return user, token
