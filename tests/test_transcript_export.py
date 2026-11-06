import httpx
import pytest
import respx

from nanosamurai_sdk import cli
from nanosamurai_sdk.client import NanosamuraiClient
from nanosamurai_sdk.errors import ApiError

ISSUER = "https://auth.example/realms/test"
SESSION_ID = "11111111-1111-1111-1111-111111111111"
EXPORT_URL = f"https://platform.example/api/recordings/{SESSION_ID}/export"


def _client() -> NanosamuraiClient:
    respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
        return_value=httpx.Response(
            200, json={"issuer": ISSUER, "token_endpoint": f"{ISSUER}/protocol/openid-connect/token"}
        )
    )
    respx.post(f"{ISSUER}/protocol/openid-connect/token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
    )
    return NanosamuraiClient(
        api_url="https://platform.example", issuer=ISSUER, client_id="c", client_secret="s"
    )


@respx.mock
def test_export_transcript_sends_format_stage_and_track() -> None:
    route = respx.get(EXPORT_URL).mock(return_value=httpx.Response(200, content=b"WEBVTT\n\n"))

    content = _client().export_transcript(SESSION_ID, "vtt", stage="refined", track_id="whisperx")

    assert content == b"WEBVTT\n\n"
    request = route.calls.last.request
    assert dict(request.url.params) == {"format": "vtt", "stage": "refined", "track_id": "whisperx"}
    assert request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_export_transcript_raises_api_error_for_unreadable_session() -> None:
    respx.get(EXPORT_URL).mock(return_value=httpx.Response(404, json={"ok": False, "message": "not-found"}))

    with pytest.raises(ApiError) as err:
        _client().export_transcript(SESSION_ID, "srt")
    assert err.value.status_code == 404


def test_export_transcript_rejects_unknown_format() -> None:
    client = NanosamuraiClient(
        api_url="https://platform.example", issuer=ISSUER, client_id="c", client_secret="s"
    )
    with pytest.raises(ValueError):
        client.export_transcript(SESSION_ID, "pdf")


def test_cli_recordings_export_writes_file(monkeypatch, tmp_path) -> None:
    calls = []

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def export_transcript(self, session_id, format, *, stage=None, track_id=None) -> bytes:
            calls.append((session_id, format, stage, track_id))
            return b"1\n00:00:00,000 --> 00:00:01,000\nHi\n\n"

    monkeypatch.setattr(cli, "NanosamuraiClient", FakeClient)
    out = tmp_path / "t.srt"

    with pytest.raises(SystemExit) as exit_info:
        cli.main(
            [
                "--api-url", "http://127.0.0.1:8000",
                "--issuer", "http://127.0.0.1:8080/realms/nanosamurai",
                "--client-id", "c",
                "--client-secret", "s",
                "recordings", "export", SESSION_ID, "--format", "srt", "--track-id", "whisperx",
                "--out", str(out),
            ]
        )

    assert exit_info.value.code == 0
    assert calls == [(SESSION_ID, "srt", None, "whisperx")]
    assert out.read_bytes().startswith(b"1\n00:00:00,000")
