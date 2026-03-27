import httpx
import pytest
import respx

from nanosamurai_sdk.client import NanosamuraiClient


@respx.mock
def test_get_recording_audio_bytes() -> None:
    issuer = "https://auth.example/realms/test"
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    token_endpoint = "https://auth.example/realms/test/protocol/openid-connect/token"

    respx.get(discovery_url).mock(
        return_value=httpx.Response(200, json={"issuer": issuer, "token_endpoint": token_endpoint})
    )
    respx.post(token_endpoint).mock(return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3600}))

    session_id = "11111111-1111-1111-1111-111111111111"
    respx.get(f"https://platform.example/api/recordings/{session_id}/audio").mock(
        return_value=httpx.Response(200, content=b"RIFF....WAVE")
    )

    client = NanosamuraiClient(
        api_url="https://platform.example",
        issuer=issuer,
        client_id="c",
        client_secret="s",
    )

    audio = client.get_recording_audio_bytes(session_id)
    assert audio.startswith(b"RIFF")


@respx.mock
def test_download_recording_audio_writes_file(tmp_path) -> None:
    issuer = "https://auth.example/realms/test"
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    token_endpoint = "https://auth.example/realms/test/protocol/openid-connect/token"

    respx.get(discovery_url).mock(
        return_value=httpx.Response(200, json={"issuer": issuer, "token_endpoint": token_endpoint})
    )
    respx.post(token_endpoint).mock(return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3600}))

    session_id = "11111111-1111-1111-1111-111111111111"
    content = b"RIFF....WAVE" + (b"x" * 1024)
    respx.get(f"https://platform.example/api/recordings/{session_id}/audio").mock(
        return_value=httpx.Response(200, content=content)
    )

    client = NanosamuraiClient(
        api_url="https://platform.example",
        issuer=issuer,
        client_id="c",
        client_secret="s",
    )

    out = tmp_path / "out.wav"
    client.download_recording_audio(session_id, str(out), chunk_size=64)
    assert out.read_bytes() == content


def test_range_end_without_start_rejected() -> None:
    client = NanosamuraiClient(
        api_url="https://platform.example",
        issuer="https://auth.example/realms/test",
        client_id="c",
        client_secret="s",
    )

    with pytest.raises(ValueError):
        _ = client.get_recording_audio_bytes("sid", range_end=10)
