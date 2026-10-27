import json

import httpx
import pytest
import respx

from nanosamurai_sdk.client import NanosamuraiClient
from nanosamurai_sdk.errors import ApiError

SESSION_ID = "11111111-1111-1111-1111-111111111111"


def _client() -> NanosamuraiClient:
    client = NanosamuraiClient(
        api_url="https://platform.example",
        issuer="https://auth.example/realms/test",
        client_id="c",
        client_secret="s",
    )
    client.get_access_token = lambda: "tok"  # type: ignore[method-assign]
    return client


@respx.mock
def test_set_session_access_sends_complete_audience() -> None:
    route = respx.put(f"https://platform.example/api/sessions/{SESSION_ID}/access").mock(
        return_value=httpx.Response(200, json={"ok": True, "session_id": SESSION_ID,
                                               "visibility": "selected", "revision": 1,
                                               "is_owner": True, "can_manage": True,
                                               "recipients": []}))
    response = _client().set_session_access(SESSION_ID, visibility="selected", revision=0,
                                            recipient_ids=["22222222-2222-2222-2222-222222222222"])
    assert route.called
    assert json.loads(route.calls.last.request.content) == {
        "visibility": "selected", "revision": 0,
        "recipient_ids": ["22222222-2222-2222-2222-222222222222"]}
    assert response["revision"] == 1


def test_set_session_access_rejects_unknown_visibility() -> None:
    with pytest.raises(ValueError):
        _client().set_session_access(SESSION_ID, visibility="public", revision=0)


@respx.mock
def test_stale_revision_is_reported() -> None:
    respx.put(f"https://platform.example/api/sessions/{SESSION_ID}/access").mock(
        return_value=httpx.Response(409, json={"ok": False, "message": "access-changed", "revision": 3}))
    with pytest.raises(ApiError) as failure:
        _client().set_session_access(SESSION_ID, visibility="tenant", revision=1)
    assert failure.value.status_code == 409


@respx.mock
def test_list_recordings_scope_is_sent() -> None:
    route = respx.get("https://platform.example/api/recordings?limit=5&offset=0&scope=shared").mock(
        return_value=httpx.Response(200, json={"ok": True, "tenant_id": SESSION_ID, "total": 0,
                                               "drafts_count": 0, "items": []}))
    assert _client().list_recordings(limit=5, scope="shared") == []
    assert route.called
    with pytest.raises(ValueError):
        _client().list_recordings(scope="everyone")
