from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(title="Demo FastAPI Service", version="1.0.0")


class Item(BaseModel):
    id: int
    name: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ping")
async def ping() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/items", response_model=list[Item])
async def list_items() -> list[Item]:
    return [
        Item(id=1, name="alpha"),
        Item(id=2, name="beta"),
    ]
