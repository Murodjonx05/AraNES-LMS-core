from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.settings import APP
from src.loader import all_routes
from src.startup import lifespan
from src.settings import SECURITY


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware,
    allow_origins = APP.CORS.get("ALLOW_ORIGINS"),
    allow_credentials = APP.CORS.get("ALLOW_CREDENTIALS"),
    allow_methods = APP.CORS.get("ALLOW_METHODS"),
    allow_headers = APP.CORS.get("ALLOW_HEADERS"),
)

app.include_router(all_routes)
SECURITY.handle_errors(app)
