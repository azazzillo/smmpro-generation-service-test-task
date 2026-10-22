from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.db import SessionLocal

router = APIRouter()


@router.get("/tasks/{task_id}")
async def get_task(task_id: UUID):
    async with SessionLocal() as s:
        task = (
            await s.execute(
                text("""
                    SELECT t.id, t.user_id, t.model_slug, t.status, t.price, t.result_url,
                           t.current_leg_priority, l.provider AS current_provider,
                           t.created_at, t.finished_at
                    FROM tasks t
                    LEFT JOIN model_legs l
                           ON l.model_slug = t.model_slug AND l.priority = t.current_leg_priority
                    WHERE t.id = CAST(:id AS uuid)
                """),
                {"id": str(task_id)},
            )
        ).mappings().first()
        if task is None:
            raise HTTPException(404, "task not found")
        attempts = (
            await s.execute(
                text("""
                    SELECT a.id, a.provider, l.priority AS leg_priority, a.status,
                           a.error_type, a.external_id, a.created_at, a.finished_at
                    FROM attempts a JOIN model_legs l ON l.id = a.leg_id
                    WHERE a.task_id = CAST(:id AS uuid)
                    ORDER BY a.id
                """),
                {"id": str(task_id)},
            )
        ).mappings().all()
    return {**task, "attempts": [dict(a) for a in attempts]}


@router.get("/users/{user_id}/balance")
async def get_balance(user_id: int):
    async with SessionLocal() as s:
        user = (
            await s.execute(text("SELECT id, balance FROM users WHERE id = :u"), {"u": user_id})
        ).mappings().first()
        if user is None:
            raise HTTPException(404, "user not found")
        ledger = (
            await s.execute(
                text("""
                    SELECT id, delta, kind, ref_id, created_at
                    FROM ledger WHERE user_id = :u ORDER BY id DESC LIMIT 20
                """),
                {"u": user_id},
            )
        ).mappings().all()
    return {"user_id": user["id"], "balance": user["balance"], "ledger": [dict(r) for r in ledger]}