import hashlib, hmac
from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/webhooks/providers/{name}")
async def hook(name: str, request: Request):
    raw = await request.body()
    expected = hmac.new(b"dev-secret", raw, hashlib.sha256).hexdigest()
    ok = hmac.compare_digest(expected, request.headers.get("X-Signature", ""))
    print(name, "SIG_OK" if ok else "SIG_BAD", raw.decode(), flush=True)
    return {"ok": True}
