import uvicorn

from src.config import build_app_config

if __name__ == "__main__":
    app_config = build_app_config()
    uvicorn.run("src.app:get_app", factory=True, host=app_config.HOST, port=app_config.PORT, reload=True)
