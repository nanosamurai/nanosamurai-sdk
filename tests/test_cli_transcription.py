from types import SimpleNamespace

import pytest

from nanosamurai_sdk import cli


def _args(*, stop_on_final: bool) -> SimpleNamespace:
    return SimpleNamespace(
        path="synthetic.wav",
        session_id=None,
        lang="en",
        sample_rate=16000,
        realtime="true",
        refined="true",
        final="true",
        store_recording="true",
        refinement_window_sec=None,
        rt_partial_enable=None,
        window_size=None,
        overlap=None,
        emit_every=None,
        stop_on_final=stop_on_final,
        event_idle_timeout_s=2.0,
        completion_timeout_s=30.0,
        completion_poll_interval_s=0.1,
    )


@pytest.mark.asyncio
async def test_cli_waits_for_persisted_completion_by_default(monkeypatch, capsys) -> None:
    calls: list[dict] = []

    class _Client:
        def create_session(self) -> str:
            return "session-id"

        async def transcribe_pcm_until_complete(self, **kwargs):
            calls.append(kwargs)
            kwargs["on_event"]({"type": "status", "status": "started"})
            return {"session": {"status": "finished", "has_final_transcript": True}}

    monkeypatch.setattr(cli, "_build_client", lambda _args: _Client())
    monkeypatch.setattr(cli, "wav_to_pcm_frames", lambda *_args, **_kwargs: [b"audio"])

    result = await cli._cmd_transcribe_wav(_args(stop_on_final=False))

    assert result == 0
    assert len(calls) == 1
    assert calls[0]["session_id"] == "session-id"
    assert calls[0]["final"] is True
    assert calls[0]["event_idle_timeout_s"] == 2.0
    assert '"status": "started"' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cli_stop_on_final_closes_stream_and_finishes_session(monkeypatch) -> None:
    stream_closed = False
    finished: list[str] = []

    class _Client:
        def create_session(self) -> str:
            return "session-id"

        async def transcribe_pcm(self, **_kwargs):
            nonlocal stream_closed
            try:
                yield {"type": "asr", "final": True}
                yield {"type": "asr", "final": False}
            finally:
                stream_closed = True

        def finish_session(self, session_id: str) -> dict:
            finished.append(session_id)
            return {"ok": True, "session_id": session_id, "status": "finished"}

    monkeypatch.setattr(cli, "_build_client", lambda _args: _Client())
    monkeypatch.setattr(cli, "wav_to_pcm_frames", lambda *_args, **_kwargs: [b"audio"])

    result = await cli._cmd_transcribe_wav(_args(stop_on_final=True))

    assert result == 0
    assert stream_closed is True
    assert finished == ["session-id"]
