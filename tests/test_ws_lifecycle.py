import asyncio
import json

import pytest

from nanosamurai_sdk.client import NanosamuraiClient
from nanosamurai_sdk.errors import ApiError, WsError
from nanosamurai_sdk.streaming import completion_ready


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

    async def _transcribe(_query, _frames, state, _idle):
        state.audio_bytes = 32000
        state.audio_sent = True
        yield event
        yield {"type": "status", "status": "stopped", "track": "faster-whisper"}
        await asyncio.Event().wait()

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
                "stream_controls": {
                    "realtime": True,
                    "refined": True,
                    "final": True,
                    "realtime_tracks": ["faster-whisper"],
                    "refinement_tracks": ["whisperx"],
                    "final_tracks": ["whisperx"],
                },
            },
            "transcripts": {
                "refined": [{"track_id": "whisperx", "segment_end_s": 1}],
                "final": [{"track_id": "whisperx"}] if ready else [],
            },
        }

    async def _on_event(value: dict) -> None:
        callbacks.append(value)

    monkeypatch.setattr(client, "_stream_pcm", _transcribe)
    monkeypatch.setattr(client, "finish_session", _finish)
    monkeypatch.setattr(client, "get_recording", _detail)

    result = await client.transcribe_pcm_until_complete(
        session_id=session_id,
        pcm_frames=[b"audio"],
        on_event=_on_event,
        completion_timeout_s=1,
        completion_poll_interval_s=0.001,
    )

    assert callbacks[0] == event
    assert len(callbacks) == 2
    assert finish_calls == [session_id]
    assert detail_calls == 2
    assert result["session"]["has_final_transcript"] is True


def test_completion_requires_every_track_and_refinement_tail():
    detail = {
        "session": {
            "status": "finished",
            "has_final_transcript": True,
            "stream_controls": {
                "realtime": True,
                "refined": True,
                "final": True,
                "realtime_tracks": ["rt-a", "rt-b"],
                "refinement_tracks": ["batch-a", "batch-b"],
                "final_tracks": ["batch-a", "batch-b"],
            },
        },
        "transcripts": {
            "refined": [
                {"track_id": "batch-a", "segment_end_s": 12},
                {"track_id": "batch-b", "segment_end_s": 11},
            ],
            "final": [{"track_id": "batch-a"}],
        },
    }
    assert not completion_ready(detail, {"rt-a"}, 12)
    assert not completion_ready(detail, {"rt-a", "rt-b"}, 12)
    detail["transcripts"]["final"].append({"track_id": "batch-b"})
    assert not completion_ready(detail, {"rt-a", "rt-b"}, 12)
    detail["transcripts"]["refined"][1]["segment_end_s"] = 12
    assert not completion_ready(detail, {"rt-b"}, 12)
    assert completion_ready(detail, {"rt-b", "rt-a"}, 12)


@pytest.mark.asyncio
async def test_finite_frames_are_paced_to_avoid_ingress_overflow(monkeypatch):
    client = _client()
    events = _EventsWs()
    sent_at = []

    class Audio(_AudioWs):
        async def send(self, payload):
            sent_at.append(asyncio.get_running_loop().time())

    sockets = iter([events, Audio()])

    async def connect(_url):
        return next(sockets)

    monkeypatch.setattr(client, "_ws_connect", connect)
    async for _ in client.transcribe_pcm(session_id="s", pcm_frames=[b"a" * 320] * 4,
                                         event_idle_timeout_s=.001):
        pass
    assert len(sent_at) == 4
    assert sent_at[-1] - sent_at[0] >= .025


def test_disabled_stages_do_not_require_selected_tracks():
    detail = {
        "session": {
            "status": "finished",
            "stream_controls": {
                "realtime": False,
                "refined": False,
                "final": False,
                "realtime_tracks": ["rt-a"],
                "refinement_tracks": ["batch-a"],
                "final_tracks": ["batch-a"],
            },
        }
    }
    assert completion_ready(detail, set(), 12)
    del detail["session"]["stream_controls"]
    assert not completion_ready(detail, set(), 12)


@pytest.mark.asyncio
async def test_continuous_events_do_not_extend_completion_deadline(monkeypatch):
    client = _client()
    closed = asyncio.Event()
    finishes = []

    async def stream(_query, _frames, state, _idle):
        state.audio_sent = True
        try:
            while True:
                yield {"type": "asr", "final": True, "track": "rt-a"}
                await asyncio.sleep(0.001)
        finally:
            closed.set()

    monkeypatch.setattr(client, "_stream_pcm", stream)
    monkeypatch.setattr(client, "finish_session", lambda sid: finishes.append(sid))
    monkeypatch.setattr(
        client,
        "get_recording",
        lambda _sid: {"session": {"status": "finished", "has_final_transcript": True}},
    )
    with pytest.raises(ApiError, match="Timed out"):
        await asyncio.wait_for(
            client.transcribe_pcm_until_complete(
                session_id="s",
                pcm_frames=[],
                completion_timeout_s=0.08,
                completion_poll_interval_s=0.005,
            ),
            timeout=1,
        )
    assert closed.is_set()
    assert finishes == ["s"]


@pytest.mark.asyncio
async def test_audio_handshake_failure_closes_events(monkeypatch):
    client = _client()
    events = _EventsWs()

    async def connect(url):
        if "/ws/audio" in url:
            raise WsError("audio rejected")
        return events

    monkeypatch.setattr(client, "_ws_connect", connect)
    with pytest.raises(WsError, match="audio rejected"):
        async for _ in client.transcribe_pcm(session_id="s", pcm_frames=[]):
            pass
    assert events._closed.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["callback", "provider", "sender", "cancel"])
async def test_finite_failure_closes_both_sockets_and_finishes(monkeypatch, failure):
    client = _client()
    events = _EventsWs([{"type": "error" if failure == "provider" else "status"}])
    audio = _AudioWs(error=RuntimeError("send failed") if failure == "sender" else None)
    sockets = iter([events, audio])
    finishes = []

    async def connect(_url):
        return next(sockets)

    def callback(_event):
        if failure == "callback":
            raise ValueError("callback failed")

    monkeypatch.setattr(client, "_ws_connect", connect)
    monkeypatch.setattr(client, "finish_session", lambda sid: finishes.append(sid))
    monkeypatch.setattr(client, "get_recording", lambda _sid: {"session": {"status": "active"}})
    task = asyncio.create_task(
        client.transcribe_pcm_until_complete(
            session_id="s",
            pcm_frames=[b"audio"],
            on_event=callback,
            completion_timeout_s=1,
            completion_poll_interval_s=0.001,
        )
    )
    if failure == "cancel":
        await asyncio.sleep(0.02)
        task.cancel()
    expected = {
        "callback": ValueError,
        "provider": WsError,
        "sender": WsError,
        "cancel": asyncio.CancelledError,
    }[failure]
    with pytest.raises(expected):
        await task
    assert events._closed.is_set() and audio.closed
    assert finishes == ["s"]
