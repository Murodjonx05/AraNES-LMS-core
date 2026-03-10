"""Constants for plugin URLs and prefixes. Kept in sync with gateway_server for /plg/ prefix."""

PUBLIC_PLUGIN_PREFIX = "/plg"


def plugin_mount_prefix(service_name: str) -> str:
    """Return the public URL prefix for a plugin service (e.g. /plg/demo_fastapi)."""
    normalized = (service_name or "").strip().strip("/")
    return f"{PUBLIC_PLUGIN_PREFIX}/{normalized}" if normalized else f"{PUBLIC_PLUGIN_PREFIX}/"
