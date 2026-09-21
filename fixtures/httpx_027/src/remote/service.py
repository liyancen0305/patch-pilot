import httpx

from .client import make_client


def fetch_profile(transport: httpx.BaseTransport, user_id: int) -> str:
    with make_client(transport) as client:
        response = client.get(f"https://example.invalid/users/{user_id}")
        response.raise_for_status()
        return str(response.json()["name"]).strip()
