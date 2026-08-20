import asyncio
import json

import pytest

from nanosamurai_sdk.client import NanosamuraiClient
from nanosamurai_sdk.errors import WsError


def _client() -> NanosamuraiClient:
    client = NanosamuraiClient(
        api_url="https://platform.example",
        issuer="https://auth.example/realms/test",
        client_id="c",
        client_secret="s",
    )
    client.get_access_token = lambda: "tok"  # type: ignore[method-assign]
    return client


class _EventsWs:
    def __init__(self, messages: list[dict] | None = None) -> None:
        self._messages = [json.dumps(message) for message in (messages or [])]
        self._closed = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._messages:
            return self._messages.pop(0)
        await self._closed.wait()
        raise StopAsyncIteration

    async def close(self) -> None:
        self._closed.set()


class _AudioWs:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.closed = False

    async def send(self, _payload: bytes) -> None:
        if self.error is not None:
            raise self.error

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_transcribe_pcm_propagates_audio_sender_failure(monkeypatch) -> None:
    client = _client()
    events_ws = _EventsWs()
    audio_ws = _AudioWs(error=RuntimeError("send failed"))
    sockets = iter([events_ws, audio_ws])

    async def _connect(_url: str):
        return next(sockets)

    monkeypatch.setattr(client, "_ws_connect", _connect)

    with pytest.raises(WsError, match="Audio streaming failed") as error:
        async for _event in client.transcribe_pcm(
            session_id="11111111-1111-1111-1111-111111111111",
            pcm_frames=[b"audio"],
        ):
            pass

    assert isinstance(error.value.__cause__, RuntimeError)


@pytest.mark.asyncio
async def test_transcribe_pcm_closes_events_after_post_audio_idle(monkeypatch) -> None:
    client = _client()
    status = {
        "type": "status",
        "status": "started",
        "session_id": "11111111-1111-1111-1111-111111111111",
        "seq": 1,
        "ts_ms": 1,
    }
    events_ws = _EventsWs([status])
    audio_ws = _AudioWs()
    sockets = iter([events_ws, audio_ws])

    async def _connect(_url: str):
        return next(sockets)

    monkeypatch.setattr(client, "_ws_connect", _connect)

    received = [
        event
        async for event in client.transcribe_pcm(
            session_id=status["session_id"],
            pcm_frames=[b"audio"],
            event_idle_timeout_s=0.01,
        )
    ]

    assert received == [status]
    assert audio_ws.closed is True


@pytest.mark.asyncio
async def test_transcribe_pcm_until_complete_finishes_and_polls(monkeypatch) -> None:
    client = _client()
    session_id = "11111111-1111-1111-1111-111111111111"
    event = {"type": "asr", "final": True, "session_id": session_id}
    callbacks: list[dict] = []
    finish_calls: list[str] = []
    detail_calls = 0

    async def _transcribe(**_kwargs):
        yield event

    def _finish(sid: str) -> dict:
        finish_calls.append(sid)
        return {"ok": True, "session_id": sid, "status": "finished"}

    def _detail(_sid: str) -> dict:
        nonlocal detail_calls
        detail_calls += 1
        ready = detail_calls > 1
        return {
            "ok": True,
            "session": {
                "status": "finished" if ready else "active",
                "has_final_transcript": ready,
            },
            "transcripts": {"refined": [], "final": []},
        }

    async def _on_event(value: dict) -> None:
        callbacks.append(value)

    monkeypatch.setattr(client, "transcribe_pcm", _transcribe)
    monkeypatch.setattr(client, "finish_session", _finish)
    monkeypatch.setattr(client, "get_recording", _detail)

    result = await client.transcribe_pcm_until_complete(
        session_id=session_id,
        pcm_frames=[b"audio"],
        on_event=_on_event,
        event_idle_timeout_s=0.01,
        completion_timeout_s=1,
        completion_poll_interval_s=0.001,
    )

    assert callbacks == [event]
    assert finish_calls == [session_id]
    assert detail_calls == 2
    assert result["session"]["has_final_transcript"] is True
