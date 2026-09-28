import httpx
import pytest

import respx

from nanosamurai_sdk.client import NanosamuraiClient


def _client() -> NanosamuraiClient:
    # Note: we avoid token minting by monkeypatching get_access_token in tests.
    return NanosamuraiClient(
        api_url="https://platform.example",
        issuer="https://auth.example/realms/test",
        client_id="c",
        client_secret="s",
    )


@respx.mock
def test_webhooks_crud_endpoints(monkeypatch) -> None:
    client = _client()
    monkeypatch.setattr(client, "get_access_token", lambda: "tok")

    respx.get("https://platform.example/api/webhooks").mock(
        return_value=httpx.Response(200, json={"ok": True, "tenant_id": "t", "items": []})
    )
    assert client.list_webhooks()["items"] == []

    respx.post("https://platform.example/api/webhooks").mock(
        return_value=httpx.Response(200, json={"ok": True, "webhook_id": "w"})
    )
    assert client.create_webhook({"name": "x"})["webhook_id"] == "w"

    respx.put("https://platform.example/api/webhooks/abc").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    assert client.update_webhook("abc", {"enabled": True})["ok"] is True

    respx.delete("https://platform.example/api/webhooks/abc").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    assert client.delete_webhook("abc")["ok"] is True

    respx.get("https://platform.example/api/webhooks/defaults").mock(
        return_value=httpx.Response(200, json={"ok": True, "tenant_id": "t", "webhook_ids": []})
    )
    assert client.get_webhook_defaults()["webhook_ids"] == []

    respx.put("https://platform.example/api/webhooks/defaults").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    assert client.set_webhook_defaults(["id1", "id2"])["ok"] is True


@respx.mock
def test_workflows_crud_endpoints(monkeypatch) -> None:
    client = _client()
    monkeypatch.setattr(client, "get_access_token", lambda: "tok")

    respx.get("https://platform.example/api/workflows").mock(
        return_value=httpx.Response(200, json={"ok": True, "tenant_id": "t", "items": []})
    )
    assert client.list_workflows()["items"] == []

    respx.post("https://platform.example/api/workflows").mock(
        return_value=httpx.Response(200, json={"ok": True, "workflow_id": "wf"})
    )
    assert client.create_workflow({"name": "x", "trigger": {
        "type": "transcript.final.ready", "track_id": "whisperx"}})["workflow_id"] == "wf"

    respx.put("https://platform.example/api/workflows/abc").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    assert client.update_workflow("abc", {"enabled": True})["ok"] is True

    respx.delete("https://platform.example/api/workflows/abc").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    assert client.delete_workflow("abc")["ok"] is True

    respx.get("https://platform.example/api/workflows/defaults").mock(
        return_value=httpx.Response(200, json={"ok": True, "tenant_id": "t", "workflow_ids": []})
    )
    assert client.get_workflow_defaults()["workflow_ids"] == []

    respx.put("https://platform.example/api/workflows/defaults").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    assert client.set_workflow_defaults(["id1", "id2"])["ok"] is True


@pytest.mark.parametrize("trigger", [None, {"type": "transcript.final.ready"},
    {"type": "transcript.refined.segment", "track_id": ""},
    {"type": "recording.finished", "track_id": "whisperx"}])
def test_invalid_workflow_trigger_rejected_before_network(trigger):
    with pytest.raises(ValueError):
        _client().create_workflow({"name": "invalid", "trigger": trigger})
