import json

from fastapi import HTTPException
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal
from app.services.attempts import dispatch


async def generate(user_id: int, model_slug: str, prompt: str, ref_images: list[str]) -> str:
    async with SessionLocal.begin() as s:
        legs = (
            await s.execute(
                text("""
                    SELECT l.id AS leg_id, l.priority, l.provider, l.max_ref_images, m.price
                    FROM models m JOIN model_legs l ON l.model_slug = m.slug
                    WHERE m.slug = :slug
                    ORDER BY l.priority
                """),
                {"slug": model_slug},
            )
        ).mappings().all()
        if not legs:
            raise HTTPException(404, "unknown model")
        eligible = [l for l in legs if l["max_ref_images"] >= len(ref_images)]
        if not eligible:
            raise HTTPException(400, "no leg accepts this many reference images")
        first, price = eligible[0], eligible[0]["price"]


        locked = (
            await s.execute(text("SELECT id FROM users WHERE id = :u FOR UPDATE"), {"u": user_id})
        ).first()
        if locked is None:
            raise HTTPException(404, "unknown user")

        active = (
            await s.execute(
                text("SELECT count(*) FROM tasks WHERE user_id = :u AND status = 'running'"),
                {"u": user_id},
            )
        ).scalar_one()
        if active >= settings.max_active_tasks:
            raise HTTPException(429, "too many active tasks")

        paid = (
            await s.execute(
                text("""
                    UPDATE users SET balance = balance - :p
                    WHERE id = :u AND balance >= :p
                    RETURNING id
                """),
                {"p": price, "u": user_id},
            )
        ).first()
        if paid is None:
            raise HTTPException(402, "insufficient tokens")

        task_id = str(
            (
                await s.execute(
                    text("""
                        INSERT INTO tasks (user_id, model_slug, prompt, ref_images, price,
                                           current_leg_priority)
                        VALUES (:u, :m, :prompt, CAST(:refs AS jsonb), :price, :prio)
                        RETURNING id
                    """),
                    {"u": user_id, "m": model_slug, "prompt": prompt,
                     "refs": json.dumps(ref_images), "price": price, "prio": first["priority"]},
                )
            ).scalar_one()
        )
        await s.execute(
            text("""
                INSERT INTO ledger (user_id, delta, kind, ref_id)
                VALUES (:u, :delta, 'charge', :ref)
            """),
            {"u": user_id, "delta": -price, "ref": task_id},
        )
        attempt_id = (
            await s.execute(
                text("""
                    INSERT INTO attempts (task_id, leg_id, provider, deadline_at)
                    VALUES (:t, :leg, :prov, now() + make_interval(secs => :secs))
                    RETURNING id
                """),
                {"t": task_id, "leg": first["leg_id"], "prov": first["provider"],
                 "secs": float(settings.provider_timeout)},
            )
        ).scalar_one()

    await dispatch(attempt_id)
    return task_id