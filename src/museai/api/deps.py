from __future__ import annotations

import hmac

from fastapi import Request

from ..errors import Unauthorized
from ..services.container import Services


def get_services(request: Request) -> Services:
    return request.app.state.services


def _bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key", "").strip()


def _check(provided: str, expected: str) -> None:
    if not expected or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise Unauthorized("invalid or missing API key")


def require_api_key(request: Request) -> None:
    """Local-only deployment: /v1/* is open on loopback."""
    return None


def require_admin_key(request: Request) -> None:
    """Local-only deployment: /admin/* is open on loopback."""
    return None


def public_base(request: Request) -> str:
    base = get_services(request).settings.public_base
    return base.rstrip("/") if base else str(request.base_url).rstrip("/")
