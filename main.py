import uvicorn
from src.settings import APP

if __name__ == "__main__":
    uvicorn.run("src.app:app", host=APP.HOST, port=APP.PORT, reload=True)