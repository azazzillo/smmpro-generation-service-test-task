import pytest


@pytest.mark.asyncio
async def test_balance_matches_ledger(client, db):
    response = await client.get("/dev/invariant")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["violations"] == []
