import asyncio
from urllib.parse import parse_qs, urlparse

import pytest

from nanosamurai_sdk.client import NanosamuraiClient


@pytest.mark.asyncio
async def test_transcribe_pcm_includes_rt_overrides_in_audio_ws_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # Capture WS urls the client tries to connect to.
    urls: list[str] = []

    class _DummyWs:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def close(self):
            return None

        async def send(self, _payload: bytes):
            return None

    async def _fake_connect(url: str):
        urls.append(url)
        return _DummyWs()

    client = NanosamuraiClient(
        api_url="https://platform.nanosamur.ai",
        issuer="https://auth.nanosamur.ai/realms/nanosamurai",
        client_id="x",
        client_secret="y",
    )

    # Avoid real token minting.
    monkeypatch.setattr(client, "get_access_token", lambda: "token")
    # Avoid real WS networking.
    monkeypatch.setattr(client, "_ws_connect", _fake_connect)

    frames = [b"1234"]

    # Consume zero events; we only care that the WS URLs are constructed correctly.
    gen = client.transcribe_pcm(
        session_id="00000000-0000-0000-0000-000000000000",
        pcm_frames=frames,
        lang="en",
        sample_rate=16000,
        window_size=5.0,
        overlap=0.5,
        emit_every=0.7,
    )

    # Trigger the async generator so it actually constructs and connects the sockets.
    async for _evt in gen:
        break

    # Expect: /ws/events and /ws/audio were both opened.
    assert any("/ws/events" in u for u in urls)
    audio_urls = [u for u in urls if "/ws/audio" in u]
    assert len(audio_urls) == 1

    parsed = urlparse(audio_urls[0])
    qs = parse_qs(parsed.query)
    assert qs["rt_window_sec"] == ["5.0"]
    assert qs["rt_overlap_sec"] == ["0.5"]
    assert qs["rt_emit_every_sec"] == ["0.7"]
