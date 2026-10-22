import httpx

from app.config import settings


class ProviderError(Exception):
    """Синхронный отказ провайдера: 5xx, таймаут, сеть. Ведёт на следующую ногу."""


async def submit(provider: str, prompt: str, ref_images: list) -> str:
    url = settings.provider_urls[provider]
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
            r = await client.post(
                f"{url}/tasks", json={"prompt": prompt, "ref_images": ref_images}
            )
    except httpx.HTTPError as e:           # таймаут, отказ соединения и т.д.
        raise ProviderError(repr(e)) from e
    if r.status_code != 202:
        raise ProviderError(f"status {r.status_code}")
    try:
        return r.json()["external_id"]
    except (ValueError, KeyError) as e:
        raise ProviderError("bad response body") from e