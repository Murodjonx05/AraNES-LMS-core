import uvicorn

from src.config import build_app_config

if __name__ == "__main__":
    app_config = build_app_config()
    uvicorn.run("src.app:app", host=app_config.HOST, port=app_config.PORT, reload=True)