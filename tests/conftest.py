
import asyncio
import os

import asyncpg
import httpx
import pytest
import pytest_asyncio

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")
DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://app:app@localhost:5433/app",
)


@pytest_asyncio.fixture
async def db():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("""
            TRUNCATE TABLE
                attempts, tasks, ledger, payments, users
            RESTART IDENTITY CASCADE
        """)
        await conn.execute("""
            INSERT INTO users (id, balance)
            VALUES (1, 100)
        """)
        await conn.execute("""
            INSERT INTO ledger (user_id, delta, kind, ref_id)
            VALUES (1, 100, 'grant', 'test-initial-balance')
        """)
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=15,
    ) as http:
        yield http


@pytest_asyncio.fixture(autouse=True)
async def reset_providers():
    async with httpx.AsyncClient(timeout=10) as http:
        for port in (9001, 9002):
            response = await http.post(
                f"http://localhost:{port}/admin/reset"
            )
            response.raise_for_status()
    await asyncio.sleep(0.1)


def sign_body(body: bytes) -> str:
    import hashlib
    import hmac

    secret = os.getenv("WEBHOOK_SECRET", "dev-secret")
    return hmac.new(
        secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
