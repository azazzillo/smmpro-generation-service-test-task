import asyncio
import logging

from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal
from app.services.attempts import _resolve_in_tx, _spawn, dispatch

log = logging.getLogger("watchdog")


async def tick() -> int:
    to_dispatch: list[int] = []
    async with SessionLocal.begin() as s:
        rows = (
            await s.execute(
                text("""
                    SELECT a.id FROM attempts a JOIN tasks t ON t.id = a.task_id
                    WHERE a.status IN ('created', 'sent') AND a.deadline_at < now()
                    ORDER BY a.deadline_at
                    LIMIT 10
                    FOR UPDATE OF t SKIP LOCKED
                """)
            )
        ).mappings().all()
        for r in rows:
            still = (
                await s.execute(
                    text("""
                        SELECT 1 FROM attempts
                        WHERE id = :id AND status IN ('created','sent') AND deadline_at < now()
                    """),
                    {"id": r["id"]},
                )
            ).first()
            if still is None:
                continue
            log.info("attempt %s timed out", r["id"])
            nxt = await _resolve_in_tx(s, r["id"], "timeout", None, None)
            if nxt is not None:
                to_dispatch.append(nxt)
    for a in to_dispatch:                 
        _spawn(dispatch(a))
    return len(rows)


async def run() -> None:
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("watchdog tick failed")
        await asyncio.sleep(settings.watchdog_interval)