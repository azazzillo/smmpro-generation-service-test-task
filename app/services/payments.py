from fastapi import HTTPException
from sqlalchemy import text

from app.db import SessionLocal

SUCCESS = {"succeeded", "success", "paid", "completed"}


async def apply_payment(payment_id: str, user_id: int, tokens: int, status: str) -> dict:
    ok = status.lower() in SUCCESS
    async with SessionLocal.begin() as s:
        if (await s.execute(text("SELECT 1 FROM users WHERE id = :u"), {"u": user_id})).first() is None:
            raise HTTPException(404, "unknown user")

        inserted = (
            await s.execute(
                text("""
                    INSERT INTO payments (payment_id, user_id, tokens, status)
                    VALUES (:p, :u, :t, :st)
                    ON CONFLICT (payment_id) DO NOTHING
                    RETURNING payment_id
                """),
                {"p": payment_id, "u": user_id, "t": tokens, "st": "succeeded" if ok else status},
            )
        ).first()

        if inserted is None:
            ex = (
                await s.execute(
                    text("SELECT user_id, tokens, status FROM payments WHERE payment_id = :p FOR UPDATE"),
                    {"p": payment_id},
                )
            ).mappings().one()
            if ex["user_id"] != user_id or ex["tokens"] != tokens:
                raise HTTPException(409, "payment_id reused with different data")
            if ex["status"] != "succeeded" and ok:
                await s.execute(
                    text("UPDATE payments SET status = 'succeeded' WHERE payment_id = :p"),
                    {"p": payment_id},
                )

        credited = False
        if ok:
            led = (
                await s.execute(
                    text("""
                        INSERT INTO ledger (user_id, delta, kind, ref_id)
                        VALUES (:u, :t, 'payment', :p)
                        ON CONFLICT (kind, ref_id) DO NOTHING
                        RETURNING id
                    """),
                    {"u": user_id, "t": tokens, "p": payment_id},
                )
            ).first()
            if led is not None:
                await s.execute(
                    text("UPDATE users SET balance = balance + :t WHERE id = :u"),
                    {"t": tokens, "u": user_id},
                )
                credited = True
    return {"ok": True, "credited": credited}