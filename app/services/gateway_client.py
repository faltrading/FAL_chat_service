import httpx

from app.core.config import settings

_client: httpx.AsyncClient | None = None


async def get_gateway_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=settings.API_GATEWAY_URL,
            timeout=10.0,
        )
    return _client


async def close_gateway_client():
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


async def fetch_user_info(user_id: str, token: str) -> dict | None:
    client = await get_gateway_client()
    try:
        response = await client.get(
            f"/api/v1/users/{user_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == 200:
            return response.json()
    except httpx.HTTPError:
        pass
    return None


async def fetch_all_users(token: str) -> list[dict]:
    client = await get_gateway_client()
    try:
        response = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == 200:
            return response.json()
    except httpx.HTTPError:
        pass
    return []
