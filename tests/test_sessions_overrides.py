import httpx

import respx

from nanosamurai_sdk.client import NanosamuraiClient


@respx.mock
def test_create_session_sends_json_body_even_when_empty() -> None:
    issuer = "https://auth.example/realms/test"
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    token_endpoint = "https://auth.example/realms/test/protocol/openid-connect/token"

    respx.get(discovery_url).mock(
        return_value=httpx.Response(200, json={"issuer": issuer, "token_endpoint": token_endpoint})
    )
    respx.post(token_endpoint).mock(return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3600}))

    captured_json: dict | None = None

    def _capture(request: httpx.Request) -> httpx.Response:
        nonlocal captured_json
        if request.content:
            captured_json = json_loads_bytes(request.content)
        return httpx.Response(200, json={"session_id": "11111111-1111-1111-1111-111111111111"})

    respx.post("https://platform.example/api/sessions").mock(side_effect=_capture)

    client = NanosamuraiClient(
        api_url="https://platform.example",
        issuer=issuer,
        client_id="c",
        client_secret="s",
    )

    _sid = client.create_session()
    assert captured_json == {}


@respx.mock
def test_create_session_supports_overrides_payload() -> None:
    issuer = "https://auth.example/realms/test"
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    token_endpoint = "https://auth.example/realms/test/protocol/openid-connect/token"

    respx.get(discovery_url).mock(
        return_value=httpx.Response(200, json={"issuer": issuer, "token_endpoint": token_endpoint})
    )
    respx.post(token_endpoint).mock(return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3600}))

    captured_json: dict | None = None

    def _capture(request: httpx.Request) -> httpx.Response:
        nonlocal captured_json
        captured_json = json_loads_bytes(request.content)
        return httpx.Response(200, json={"session_id": "11111111-1111-1111-1111-111111111111"})

    respx.post("https://platform.example/api/sessions").mock(side_effect=_capture)

    client = NanosamuraiClient(
        api_url="https://platform.example",
        issuer=issuer,
        client_id="c",
        client_secret="s",
    )

    _sid = client.create_session(
        title="hello",
        session_settings={"refined_transcript": {"consolidation": {"enabled": True}}},
        webhook_overrides={
            "use_defaults": True,
            "webhook_ids": ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
            "disable_event_types": ["transcript.refined.segment"],
        },
        workflow_overrides={
            "use_defaults": False,
            "workflow_ids": ["bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"],
        },
    )

    assert isinstance(captured_json, dict)
    assert captured_json.get("title") == "hello"
    assert "session_settings" in captured_json
    assert "webhook_overrides" in captured_json
    assert "workflow_overrides" in captured_json


def json_loads_bytes(b: bytes) -> dict:
    """Parse a JSON object from bytes.

    This is kept local to avoid bringing in any additional test dependencies.
    """

    import json

    obj = json.loads(b.decode("utf-8"))
    if not isinstance(obj, dict):
        raise AssertionError("expected JSON object")
    return obj
