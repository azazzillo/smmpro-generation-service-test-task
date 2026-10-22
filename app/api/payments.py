import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.security import verified_body
from app.services.payments import apply_payment

router = APIRouter()


class PaymentEvent(BaseModel):
    payment_id: str
    user_id: int
    tokens: int = Field(gt=0)
    status: str


@router.post("/webhooks/payments")
async def payments_webhook(raw: bytes = Depends(verified_body)):
    try:
        ev = PaymentEvent(**json.loads(raw))
    except (ValueError, ValidationError):
        raise HTTPException(400, "bad payload")
    return await apply_payment(ev.payment_id, ev.user_id, ev.tokens, ev.status)