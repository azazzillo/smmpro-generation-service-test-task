from fastapi import FastAPI

from app.api import dev, generate, webhooks

app = FastAPI(title="generation-service")
app.include_router(generate.router)
app.include_router(webhooks.router)
app.include_router(dev.router)


@app.get("/health")
async def health():
    return {"ok": True}