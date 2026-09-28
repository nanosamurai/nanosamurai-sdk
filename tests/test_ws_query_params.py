import json
from urllib.parse import parse_qs, urlparse

import pytest

from nanosamurai_sdk.client import NanosamuraiClient


@pytest.mark.asyncio
async def test_transcribe_pcm_includes_track_settings_in_audio_ws_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        realtime_tracks=["faster-whisper"],
        refinement_tracks=["whisperx"],
        final_tracks=["whisperx"],
        realtime_settings={
            "faster-whisper": {"window_sec": 5.0, "overlap_sec": 0.5, "emit_every_sec": 0.7}
        },
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
    assert qs["realtime_tracks"] == ["faster-whisper"]
    assert qs["refinement_tracks"] == qs["final_tracks"] == ["whisperx"]
    assert json.loads(qs["realtime_settings"][0]) == {
        "faster-whisper": {"window_sec": 5.0, "overlap_sec": 0.5, "emit_every_sec": 0.7}
    }
    assert not any(key.startswith("rt_") for key in qs)


@pytest.mark.asyncio
async def test_transcribe_pcm_includes_stream_controls_in_audio_ws_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    monkeypatch.setattr(client, "get_access_token", lambda: "token")
    monkeypatch.setattr(client, "_ws_connect", _fake_connect)

    frames = [b"1234"]

    gen = client.transcribe_pcm(
        session_id="00000000-0000-0000-0000-000000000000",
        pcm_frames=frames,
        lang="en",
        sample_rate=16000,
        realtime=False,
        refined=True,
        final=False,
        store_recording=False,
        refinement_window_sec=42.5,
    )

    async for _evt in gen:
        break

    audio_urls = [u for u in urls if "/ws/audio" in u]
    assert len(audio_urls) == 1
    parsed = urlparse(audio_urls[0])
    qs = parse_qs(parsed.query)
    assert qs["realtime"] == ["false"]
    assert qs["refined"] == ["true"]
    assert qs["final"] == ["false"]
    assert qs["store_recording"] == ["false"]
    assert qs["refinement_window_sec"] == ["42.5"]
    assert (
        not {"realtime_tracks", "refinement_tracks", "final_tracks", "realtime_settings"}
        & qs.keys()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", [[], ["a", "a"], ["a,b"], [" a"], "a"])
async def test_invalid_track_selection_fails_before_network(selection, monkeypatch):
    client = NanosamuraiClient(
        api_url="https://example.test", issuer="https://auth.test", client_id="c", client_secret="s"
    )

    async def unexpected(_url):
        pytest.fail("Invalid input must fail before connecting")

    monkeypatch.setattr(client, "_ws_connect", unexpected)
    with pytest.raises(ValueError):
        async for _ in client.transcribe_pcm(session_id="s", pcm_frames=[], final_tracks=selection):
            pass
