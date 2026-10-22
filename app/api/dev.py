import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.db import SessionLocal

router = APIRouter(prefix="/dev", tags=["dev"])


class DevUserIn(BaseModel):
    id: int
    balance: int = Field(ge=0, default=0)


@router.post("/users")
async def create_or_topup(body: DevUserIn):
    async with SessionLocal.begin() as s:
        await s.execute(
            text("INSERT INTO users (id, balance) VALUES (:id, 0) ON CONFLICT DO NOTHING"),
            {"id": body.id},
        )
        if body.balance > 0:
            await s.execute(
                text("INSERT INTO ledger (user_id, delta, kind, ref_id) VALUES (:u, :d, 'grant', :r)"),
                {"u": body.id, "d": body.balance, "r": str(uuid.uuid4())},
            )
            await s.execute(
                text("UPDATE users SET balance = balance + :d WHERE id = :u"),
                {"u": body.id, "d": body.balance},
            )
    return {"user_id": body.id, "granted": body.balance}