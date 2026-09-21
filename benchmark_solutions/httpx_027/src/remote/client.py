import httpx


def make_client(transport: httpx.BaseTransport) -> httpx.Client:
    return httpx.Client(transport=transport, trust_env=False,
                        headers={"X-App": "PatchPilot"})
