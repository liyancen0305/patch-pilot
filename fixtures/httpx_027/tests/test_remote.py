import httpx
import pytest

from remote.service import fetch_profile


def test_profile_header_and_name() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-App"] == "PatchPilot"
        assert request.url.path == "/users/7"
        return httpx.Response(200, json={"name": " Ada "})
    assert fetch_profile(httpx.MockTransport(handle), 7) == "Ada"


def test_http_error_propagates() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        fetch_profile(transport, 7)
