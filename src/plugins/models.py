from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Model


class PluginMapping(Model):
    __tablename__ = "plugin_mappings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plugin_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    service_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    mount_prefix: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
