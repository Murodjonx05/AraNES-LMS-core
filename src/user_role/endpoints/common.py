"""Backward-compatible imports. Prefer `serializers.py`."""

from src.user_role.endpoints.serializers import serialize_role, serialize_user

__all__ = ["serialize_role", "serialize_user"]
