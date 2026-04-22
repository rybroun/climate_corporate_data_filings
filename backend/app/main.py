from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import company, resolve, search

from app.db import init_pool, close_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="Company Carbon Lookup", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- Routers ------------------------------------------------------------------
app.include_router(search.router, prefix="/api", tags=["search"])
app.include_router(company.router, prefix="/api", tags=["company"])
app.include_router(resolve.router, prefix="/api", tags=["resolve"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}
