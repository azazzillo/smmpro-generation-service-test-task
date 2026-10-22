import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import text

from app.db import SessionLocal
from app.security import verified_body
from app.services.attempts import resolve_attempt

router = APIRouter()


class ProviderEvent(BaseModel):
    external_id: str
    status: Literal["completed", "failed"]
    result_url: str | None = None
    error_type: Literal["technical", "moderation", "payload"] = "technical"


@router.post("/webhooks/providers/{name}")
async def provider_webhook(name: str, raw: bytes = Depends(verified_body)):
    try:
        ev = ProviderEvent(**json.loads(raw))
    except (ValueError, ValidationError):
        raise HTTPException(400, "bad payload")

    async with SessionLocal() as s:
        row = (
            await s.execute(
                text("SELECT id FROM attempts WHERE provider = :p AND external_id = :e"),
                {"p": name, "e": ev.external_id},
            )
        ).mappings().first()
    if row is None:
        raise HTTPException(404, "unknown external_id")

    await resolve_attempt(row["id"], ev.status, ev.error_type, ev.result_url)
    return {"ok": True}