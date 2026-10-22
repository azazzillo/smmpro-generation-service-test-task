import asyncio
import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.services import providers

log = logging.getLogger("attempts")

LIVE = ("created", "sent")
_background: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _background.add(t)
    t.add_done_callback(_background.discard)


async def resolve_attempt(
    attempt_id: int,
    outcome: str,                    
    error_type: str | None = None,   
    result_url: str | None = None,
) -> None:
    async with SessionLocal.begin() as s:
        next_attempt_id = await _resolve_in_tx(s, attempt_id, outcome, error_type, result_url)

    if next_attempt_id is not None:
        _spawn(dispatch(next_attempt_id))


async def _finish_attempt(s: AsyncSession, attempt_id: int, status: str, error_type: str | None = None):
    await s.execute(
        text("""
            UPDATE attempts SET status = :st, error_type = COALESCE(:et, error_type),
                                finished_at = now()
            WHERE id = :id
        """),
        {"st": status, "et": error_type, "id": attempt_id},
    )


async def _complete_task(s: AsyncSession, task_id, result_url: str | None):
    await s.execute(
        text("""
            UPDATE tasks SET status = 'completed', result_url = :url, finished_at = now()
            WHERE id = :t
        """),
        {"url": result_url, "t": task_id},
    )
    await s.execute(
        text("""
            UPDATE attempts SET status = 'superseded', finished_at = now()
            WHERE task_id = :t AND status IN ('created', 'sent')
        """),
        {"t": task_id},
    )


async def _fail_and_refund(s: AsyncSession, task) -> None:
    await s.execute(
        text("UPDATE tasks SET status = 'failed', finished_at = now() WHERE id = :t"),
        {"t": task["id"]},
    )

    inserted = (
        await s.execute(
            text("""
                INSERT INTO ledger (user_id, delta, kind, ref_id)
                VALUES (:u, :d, 'refund', :r)
                ON CONFLICT (kind, ref_id) DO NOTHING
                RETURNING id
            """),
            {"u": task["user_id"], "d": task["price"], "r": str(task["id"])},
        )
    ).first()
    if inserted is not None:
        await s.execute(
            text("UPDATE users SET balance = balance + :d WHERE id = :u"),
            {"d": task["price"], "u": task["user_id"]},
        )


async def _resolve_in_tx(s, attempt_id, outcome, error_type, result_url) -> int | None:
    row = (
        await s.execute(text("SELECT task_id FROM attempts WHERE id = :id"), {"id": attempt_id})
    ).mappings().first()
    if row is None:
        return None

    task = (
        await s.execute(
            text("""
                SELECT id, user_id, model_slug, ref_images, price, status
                FROM tasks WHERE id = :t FOR UPDATE
            """),
            {"t": row["task_id"]},
        )
    ).mappings().one()
    att = (
        await s.execute(
            text("""
                SELECT a.id, a.status, l.priority
                FROM attempts a JOIN model_legs l ON l.id = a.leg_id
                WHERE a.id = :id FOR UPDATE OF a
            """),
            {"id": attempt_id},
        )
    ).mappings().one()

    if outcome == "completed":
        if att["status"] in LIVE:
            if task["status"] == "running":
                await _finish_attempt(s, attempt_id, "completed")
                await _complete_task(s, task["id"], result_url)
            else:
                await _finish_attempt(s, attempt_id, "superseded")
            return None

        if att["status"] == "timeout":
            if task["status"] == "running":
                await _finish_attempt(s, attempt_id, "completed")
                await _complete_task(s, task["id"], result_url)   
            else:
                await _finish_attempt(s, attempt_id, "late_completed")
        return None   

    if att["status"] not in LIVE:
        return None                       

    if outcome == "timeout":
        error_type = "technical"
    elif error_type not in ("technical", "moderation", "payload"):
        error_type = "technical"
    await _finish_attempt(s, attempt_id, "timeout" if outcome == "timeout" else "failed", error_type)

    if task["status"] != "running":
        return None

    if error_type == "payload":
        await _fail_and_refund(s, task)
        return None

    refs = task["ref_images"]
    if isinstance(refs, str):
        refs = json.loads(refs)

    legs = (
        await s.execute(
            text("""
                SELECT id, priority, provider, max_ref_images, skip_on_moderation
                FROM model_legs
                WHERE model_slug = :m AND priority > :p
                ORDER BY priority
            """),
            {"m": task["model_slug"], "p": att["priority"]},
        )
    ).mappings().all()

    for leg in legs:
        if leg["max_ref_images"] < len(refs):
            continue
        if error_type == "moderation" and leg["skip_on_moderation"]:
            continue
        new = (
            await s.execute(
                text("""
                    INSERT INTO attempts (task_id, leg_id, provider, deadline_at)
                    VALUES (:t, :leg, :prov, now() + make_interval(secs => :secs))
                    ON CONFLICT (task_id, leg_id) DO NOTHING
                    RETURNING id
                """),
                {"t": task["id"], "leg": leg["id"], "prov": leg["provider"],
                 "secs": float(settings.provider_timeout)},
            )
        ).mappings().first()
        if new is None:
            return None
        await s.execute(
            text("UPDATE tasks SET current_leg_priority = :p WHERE id = :t"),
            {"p": leg["priority"], "t": task["id"]},
        )
        return new["id"]

    await _fail_and_refund(s, task)
    return None


async def dispatch(attempt_id: int) -> None:
    """Отправить попытку провайдеру. Вызывается ВНЕ транзакции."""
    async with SessionLocal() as s:
        row = (
            await s.execute(
                text("""
                    SELECT a.provider, a.status, t.prompt, t.ref_images
                    FROM attempts a JOIN tasks t ON t.id = a.task_id
                    WHERE a.id = :id
                """),
                {"id": attempt_id},
            )
        ).mappings().first()
    if row is None or row["status"] != "created":
        return

    refs = row["ref_images"]
    if isinstance(refs, str):
        refs = json.loads(refs)

    try:
        external_id = await providers.submit(row["provider"], row["prompt"], refs)
    except providers.ProviderError as e:
        log.info("attempt %s: sync failure %s", attempt_id, e)
        await resolve_attempt(attempt_id, "failed", "technical")
        return

    async with SessionLocal.begin() as s:
        await s.execute(
            text("""
                UPDATE attempts
                SET external_id = :ext,
                    status = CASE WHEN status = 'created' THEN 'sent' ELSE status END
                WHERE id = :id
            """),
            {"ext": external_id, "id": attempt_id},
        )