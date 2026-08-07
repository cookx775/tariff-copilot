from __future__ import annotations

from collections.abc import Mapping
from typing import Optional


class IdentityError(ValueError):
    """Raised when an actor cannot be established safely."""


def forwarded_email(headers: Mapping[str, str]) -> Optional[str]:
    for key, value in headers.items():
        if key.lower() == "x-forwarded-email":
            normalized = str(value).strip()
            return normalized or None
    return None


def actor_email(headers: Mapping[str, str], fallback: Optional[str] = None) -> str:
    forwarded = forwarded_email(headers)
    local = str(fallback or "").strip()
    candidate = forwarded or local
    if not candidate:
        raise IdentityError(
            "Databricks did not forward an actor identity; provide an explicit local identity."
        )
    return candidate
