import asyncio
import hashlib
import hmac
import json
import logging
import os
import random
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

log = logging.getLogger("provider")
logging.basicConfig(level=logging.INFO)

NAME = os.getenv("PROVIDER_NAME", "alpha")
SECRET = os.getenv("WEBHOOK_SECRET", "dev-secret")
SELF_URL = os.getenv("SELF_URL", "http://localhost:8000").rstrip("/")
WEBHOOK_URL = f"{SELF_URL}/webhooks/providers/{NAME}"


class Config(BaseModel):
    fail_rate: float = 0.0             
    error_type: str = "technical"      
    sync_mode: str = "off"             
    duplicate_webhook: bool = False 
    never_send: bool = False          
    delay_min: float = float(os.getenv("DELAY_MIN", 2))
    delay_max: float = float(os.getenv("DELAY_MAX", 20))
    sync_timeout_sleep: float = 30.0 


cfg = Config()
received: list[dict] = []
_background: set[asyncio.Task] = set()

app = FastAPI(title=f"fake-provider-{NAME}")


def sign(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


async def send_webhook(client: httpx.AsyncClient, body: bytes) -> None:
    try:
        r = await client.post(
            WEBHOOK_URL,
            content=body,
            headers={"X-Signature": sign(body), "Content-Type": "application/json"},
        )
        log.info("[%s] webhook -> %s", NAME, r.status_code)
    except httpx.HTTPError as e:
        log.warning("[%s] webhook failed: %r", NAME, e)


async def deliver(external_id: str, c: Config) -> None:
    await asyncio.sleep(random.uniform(c.delay_min, c.delay_max))
    if c.never_send:
        log.info("[%s] %s: webhook suppressed", NAME, external_id)
        return

    if random.random() < c.fail_rate:
        payload = {"external_id": external_id, "status": "failed", "error_type": c.error_type}
    else:
        payload = {
            "external_id": external_id,
            "status": "completed",
            "result_url": f"https://files.fake/{external_id}.png",
        }
    body = json.dumps(payload).encode()

    async with httpx.AsyncClient(timeout=10) as client:
        if c.duplicate_webhook:
            await asyncio.gather(send_webhook(client, body), send_webhook(client, body))
        else:
            await send_webhook(client, body)


class TaskIn(BaseModel):
    prompt: str = ""
    ref_images: list[str] = []


@app.post("/tasks", status_code=202)
async def create_task(task: TaskIn):
    c = cfg.model_copy()  
    if c.sync_mode == "timeout":
        await asyncio.sleep(c.sync_timeout_sleep)
    if c.sync_mode == "503":
        raise HTTPException(status_code=503, detail="provider unavailable")

    external_id = uuid.uuid4().hex
    received.append({"external_id": external_id, **task.model_dump()})
    t = asyncio.create_task(deliver(external_id, c))
    _background.add(t)
    t.add_done_callback(_background.discard)
    return {"external_id": external_id}


@app.get("/admin/config")
async def get_config():
    return cfg.model_dump()


@app.post("/admin/config")
async def set_config(patch: dict):
    global cfg
    cfg = Config(**{**cfg.model_dump(), **patch})
    return cfg.model_dump()


@app.post("/admin/reset")
async def reset():
    global cfg
    cfg = Config()
    received.clear()
    return cfg.model_dump()


@app.get("/admin/received")
async def get_received():
    return received


@app.get("/health")
async def health():
    return {"name": NAME, "ok": True}