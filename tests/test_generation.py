import asyncio

import pytest


async def wait_for_task(client, task_id, expected, timeout=15):
    deadline = asyncio.get_running_loop().time() + timeout

    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/tasks/{task_id}")
        assert response.status_code == 200

        task = response.json()
        if task["status"] in expected:
            return task

        await asyncio.sleep(0.2)

    pytest.fail(f"Task {task_id} did not reach {expected}")


async def configure_provider(port, config):
    import httpx

    async with httpx.AsyncClient(timeout=10) as http:
        response = await http.post(
            f"http://localhost:{port}/admin/config",
            json=config,
        )
        response.raise_for_status()


async def start_generation(client, model="image-fast"):
    response = await client.post(
        "/generate",
        json={
            "user_id": 1,
            "model_slug": model,
            "prompt": "pytest test image",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["task_id"]


@pytest.mark.asyncio
async def test_failed_generation_refunds_once(client, db):
    await configure_provider(9001, {"sync_mode": "503"})
    await configure_provider(9002, {"sync_mode": "503"})

    task_id = await start_generation(client)
    task = await wait_for_task(client, task_id, {"failed"})

    assert task["result_url"] is None

    refund_count = await db.fetchval("""
        SELECT COUNT(*) FROM ledger
        WHERE kind = 'refund' AND ref_id = $1
    """, str(task_id))

    charge_count = await db.fetchval("""
        SELECT COUNT(*) FROM ledger
        WHERE kind = 'charge' AND ref_id = $1
    """, str(task_id))

    balance = await db.fetchval(
        "SELECT balance FROM users WHERE id = 1"
    )

    assert refund_count == 1
    assert charge_count == 1
    assert balance == 100


@pytest.mark.asyncio
async def test_first_provider_failure_uses_second(
    client, db
):
    await configure_provider(9001, {"sync_mode": "503"})
    await configure_provider(9002, {"sync_mode": "off"})

    task_id = await start_generation(client)
    task = await wait_for_task(client, task_id, {"completed"})

    assert task["result_url"]

    providers = await db.fetch("""
        SELECT provider, status
        FROM attempts
        WHERE task_id = $1::uuid
        ORDER BY id
    """, str(task_id))

    assert len(providers) == 2
    assert providers[0]["provider"] == "alpha"
    assert providers[1]["provider"] == "beta"

    assert providers[0]["status"] == "failed"
    assert providers[1]["status"] == "completed"

    balance = await db.fetchval(
        "SELECT balance FROM users WHERE id = 1"
    )
    assert balance == 98


@pytest.mark.asyncio
async def test_late_completed_after_refund(client, db):
    await configure_provider(
        9001,
        {"delay_min": 8, "delay_max": 8},
    )
    await configure_provider(9002, {"sync_mode": "503"})

    task_id = await start_generation(client)

    task = await wait_for_task(
        client, task_id, {"failed"}, timeout=10
    )

    assert task["result_url"] is None

    await asyncio.sleep(8)

    attempts = await db.fetch("""
        SELECT provider, status
        FROM attempts
        WHERE task_id = $1::uuid
        ORDER BY id
    """, str(task_id))

    alpha = next(a for a in attempts if a["provider"] == "alpha")
    assert alpha["status"] == "late_completed"

    balance = await db.fetchval(
        "SELECT balance FROM users WHERE id = 1"
    )
    assert balance == 100

    refunds = await db.fetchval("""
        SELECT COUNT(*) FROM ledger
        WHERE kind = 'refund' AND ref_id = $1
    """, str(task_id))
    assert refunds == 1
