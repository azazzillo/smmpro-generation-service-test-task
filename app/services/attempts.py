import logging

from sqlalchemy import text

from app.db import SessionLocal
from app.services import providers

log = logging.getLogger("attempts")


async def resolve_attempt(attempt_id: int, outcome: str, error_type: str | None = None) -> None:
    log.warning("resolve_attempt(%s, %s, %s) not implemented yet", attempt_id, outcome, error_type)


async def dispatch(attempt_id: int) -> None:

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

    try:
        external_id = await providers.submit(row["provider"], row["prompt"], row["ref_images"])
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