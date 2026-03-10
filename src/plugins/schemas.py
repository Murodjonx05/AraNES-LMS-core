from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PluginMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plugin_name: str
    service_name: str
    mount_prefix: str
    enabled: bool
    discovered: bool
    running: bool


class PluginEnabledPatch(BaseModel):
    enabled: bool
