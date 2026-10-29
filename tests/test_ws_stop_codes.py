import asyncio

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from nanosamurai_sdk.client import NanosamuraiClient
from nanosamurai_sdk.errors import SessionStoppedError, WsError

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


def _closed(code: int) -> ConnectionClosedError:
    return ConnectionClosedError(Close(code, ""), None)


class _EventsWs:
    """Events socket that the server closes with a given error."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(0)
        raise self.error

    async def close(self) -> None:
        self.closed = True


class _AudioWs:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.closed = False

    async def send(self, _payload: bytes) -> None:
        if self.error is not None:
            raise self.error

    async def close(self) -> None:
        self.closed = True


def _patch(monkeypatch, client, *sockets) -> None:
    it = iter(sockets)

    async def _connect(_url: str):
        return next(it)

    monkeypatch.setattr(client, "_ws_connect", _connect)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "reason"),
    [(4403, "access-revoked"), (4408, "max-duration"), (4503, "access-unverified")],
)
async def test_server_stop_codes_raise_session_stopped(monkeypatch, code, reason) -> None:
    client = _client()
    _patch(monkeypatch, client, _EventsWs(_closed(code)), _AudioWs())

    with pytest.raises(SessionStoppedError) as error:
        async for _event in client.transcribe_pcm(session_id=SESSION_ID, pcm_frames=[]):
            pass

    assert error.value.close_code == code
    assert error.value.reason == reason
    assert isinstance(error.value, WsError), "existing WsError handlers keep working"


@pytest.mark.asyncio
async def test_a_stop_seen_by_the_audio_sender_is_reported(monkeypatch) -> None:
    client = _client()
    events = _EventsWs(_closed(4403))
    _patch(monkeypatch, client, events, _AudioWs(error=_closed(4403)))

    with pytest.raises(SessionStoppedError) as error:
        async for _event in client.transcribe_pcm(session_id=SESSION_ID, pcm_frames=[b"\x00\x00"]):
            pass

    assert error.value.reason == "access-revoked"


@pytest.mark.asyncio
async def test_other_closes_stay_generic(monkeypatch) -> None:
    client = _client()
    _patch(monkeypatch, client, _EventsWs(_closed(1011)), _AudioWs())

    with pytest.raises(WsError) as error:
        async for _event in client.transcribe_pcm(session_id=SESSION_ID, pcm_frames=[]):
            pass

    assert not isinstance(error.value, SessionStoppedError)


@pytest.mark.asyncio
async def test_iter_events_reports_server_stops(monkeypatch) -> None:
    client = _client()
    _patch(monkeypatch, client, _EventsWs(_closed(4408)))

    with pytest.raises(SessionStoppedError) as error:
        async for _event in client.iter_events(session_id=SESSION_ID):
            pass

    assert error.value.reason == "max-duration"
