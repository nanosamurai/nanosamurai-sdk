import httpx

import respx

from nanosamurai_sdk.client import NanosamuraiClient


def _client() -> NanosamuraiClient:
    return NanosamuraiClient(
        api_url="https://platform.example",
        issuer="https://auth.example/realms/test",
        client_id="c",
        client_secret="s",
    )


@respx.mock
def test_me_endpoint(monkeypatch) -> None:
    client = _client()
    monkeypatch.setattr(client, "get_access_token", lambda: "tok")

    respx.get("https://platform.example/api/me").mock(
        return_value=httpx.Response(200, json={"ok": True, "authenticated": True, "tenant_id": "t"})
    )

    data = client.me()
    assert data["ok"] is True


@respx.mock
def test_speakers_endpoints(monkeypatch) -> None:
    client = _client()
    monkeypatch.setattr(client, "get_access_token", lambda: "tok")

    respx.get("https://platform.example/api/speakers").mock(
        return_value=httpx.Response(200, json={"ok": True, "items": []})
    )
    assert client.list_speakers()["items"] == []

    respx.delete("https://platform.example/api/speakers/sp1").mock(
        return_value=httpx.Response(200, json={"ok": True, "speaker_id": "sp1"})
    )
    assert client.delete_speaker("sp1")["speaker_id"] == "sp1"

    respx.post("https://platform.example/api/speaker-enrollment/from-recording").mock(
        return_value=httpx.Response(200, json={"ok": True, "speaker_id": "sp2"})
    )
    assert (
        client.create_speaker_from_recording(session_id="sid", start_s=1.0, end_s=2.0, label="A")["speaker_id"]
        == "sp2"
    )


@respx.mock
def test_create_speaker_uploads_multipart_sample(monkeypatch, tmp_path) -> None:
    client = _client()
    monkeypatch.setattr(client, "get_access_token", lambda: "tok")
    sample = tmp_path / "speaker.wav"
    sample.write_bytes(b"RIFF....WAVE")

    captured: httpx.Request | None = None

    def _capture(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(200, json={"ok": True, "speaker_id": "sp3"})

    respx.post("https://platform.example/api/speakers").mock(side_effect=_capture)

    result = client.create_speaker(label="Alice", sample_path=str(sample))

    assert result["speaker_id"] == "sp3"
    assert captured is not None
    assert captured.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="label"' in captured.content
    assert b"Alice" in captured.content
    assert b'name="sample"; filename="speaker.wav"' in captured.content
    assert b"RIFF....WAVE" in captured.content


@respx.mock
def test_api_credentials_endpoints(monkeypatch) -> None:
    client = _client()
    monkeypatch.setattr(client, "get_access_token", lambda: "tok")

    respx.get("https://platform.example/api/api-credentials").mock(
        return_value=httpx.Response(200, json={"ok": True, "tenant_id": "t", "items": []})
    )
    assert client.list_api_credentials()["items"] == []

    respx.post("https://platform.example/api/api-credentials").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "credential_id": "c1", "client_id": "kid", "client_secret": "secret"},
        )
    )
    assert client.create_api_credential(name="x")["credential_id"] == "c1"

    respx.post("https://platform.example/api/api-credentials/c1/rotate").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "credential_id": "c1", "client_id": "kid", "client_secret": "secret2"},
        )
    )
    assert client.rotate_api_credential("c1")["client_secret"] == "secret2"

    respx.delete("https://platform.example/api/api-credentials/c1").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    assert client.revoke_api_credential("c1")["ok"] is True
