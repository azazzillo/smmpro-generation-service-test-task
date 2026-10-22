import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import dev, generate, payments, webhooks, reads
from app.services import watchdog


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(watchdog.run())   
    yield
    task.cancel()


app = FastAPI(title="generation-service", lifespan=lifespan)
app.include_router(generate.router)
app.include_router(webhooks.router)
app.include_router(payments.router)
app.include_router(dev.router)
app.include_router(reads.router)


@app.get("/health")
async def health():
    return {"ok": True}