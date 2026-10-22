import hashlib
import hmac

from fastapi import HTTPException, Request

from app.config import settings


def sign(body: bytes) -> str:
    return hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()


async def verified_body(request: Request) -> bytes:
    raw = await request.body()
    given = request.headers.get("X-Signature", "")
    if not hmac.compare_digest(sign(raw), given):
        raise HTTPException(status_code=401, detail="bad signature")
    return raw