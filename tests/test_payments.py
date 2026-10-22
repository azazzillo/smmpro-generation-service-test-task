
import asyncio
import json

import pytest

from conftest import sign_body


@pytest.mark.asyncio
async def test_duplicate_payment_webhooks(client, db):
    body = json.dumps(
        {
            "payment_id": "payment-concurrent-1",
            "user_id": 1,
            "tokens": 50,
            "status": "succeeded",
        },
        separators=(",", ":"),
    ).encode()

    signature = sign_body(body)

    async def send_payment():
        return await client.post(
            "/webhooks/payments",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": signature,
            },
        )

    responses = await asyncio.gather(
        *(send_payment() for _ in range(20))
    )

    assert all(r.status_code == 200 for r in responses)
    assert sum(r.json()["credited"] for r in responses) == 1

    balance = await db.fetchval(
        "SELECT balance FROM users WHERE id = 1"
    )
    payment_entries = await db.fetchval("""
        SELECT COUNT(*) FROM ledger
        WHERE kind = 'payment'
          AND ref_id = 'payment-concurrent-1'
    """)

    assert balance == 150
    assert payment_entries == 1
