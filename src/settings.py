from authx import AuthX

from src.core.config import build_app_config

APP = build_app_config()
SECURITY = AuthX(config=APP.AUTH_CONFIG)