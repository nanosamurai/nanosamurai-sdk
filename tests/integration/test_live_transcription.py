from datetime import UTC, datetime
import os
from pathlib import Path

import pytest

from nanosamurai_sdk.audio import wav_to_pcm_frames
from nanosamurai_sdk.client import NanosamuraiClient


pytestmark = pytest.mark.live


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is required for the live SDK test")
    return value


@pytest.mark.asyncio
async def test_live_transcription_reaches_persisted_final_output() -> None:
    if os.environ.get("NANOSAMURAI_RUN_LIVE_TESTS") != "1":
        pytest.skip("set NANOSAMURAI_RUN_LIVE_TESTS=1 to authorize live audio upload")

    wav_path = Path(_required_env("NANOSAMURAI_TEST_WAV"))
    if not wav_path.is_file():
        pytest.fail(f"NANOSAMURAI_TEST_WAV does not exist: {wav_path}")

    client = NanosamuraiClient(
        api_url=_required_env("NANOSAMURAI_API_URL"),
        issuer=_required_env("NANOSAMURAI_ISSUER"),
        client_id=_required_env("NANOSAMURAI_CLIENT_ID"),
        client_secret=_required_env("NANOSAMURAI_CLIENT_SECRET"),
        timeout_s=30,
    )
    session_id: str | None = None
    events: list[dict] = []

    try:
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        session_id = client.create_session(title=f"SDK live integration {timestamp}")
        renamed_title = f"SDK live integration running {timestamp}"
        rename_response = client.rename_session(session_id, title=renamed_title)
        assert rename_response["title"] == renamed_title

        detail = await client.transcribe_pcm_until_complete(
            session_id=session_id,
            pcm_frames=wav_to_pcm_frames(str(wav_path)),
            lang=os.environ.get("NANOSAMURAI_TEST_LANG", "en"),
            sample_rate=16000,
            realtime=True,
            refined=True,
            final=True,
            store_recording=True,
            on_event=events.append,
            event_idle_timeout_s=float(os.environ.get("NANOSAMURAI_TEST_EVENT_IDLE_S", "15")),
            completion_timeout_s=float(os.environ.get("NANOSAMURAI_TEST_COMPLETION_S", "240")),
        )

        session = detail["session"]
        transcripts = detail["transcripts"]
        assert session["status"] == "finished"
        assert session["title"] == renamed_title
        assert session["has_recording"] is True
        assert session["has_final_transcript"] is True
        assert transcripts["refined"]
        assert transcripts["final"]
        assert any(event.get("type") == "asr" for event in events)

        audio_prefix = client.get_recording_audio_bytes(session_id, range_start=0, range_end=43)
        assert len(audio_prefix) == 44
        assert audio_prefix.startswith(b"RIFF")

        # Exercise the configuration endpoints added alongside workflows and
        # webhooks without mutating tenant configuration.
        assert isinstance(client.list_workflows().get("items"), list)
        assert isinstance(client.list_webhooks().get("items"), list)
        assert client.get_workflow_defaults().get("ok") is True
        assert client.get_webhook_defaults().get("ok") is True
        outcomes = client.list_webhook_delivery_outcomes(session_id)
        assert isinstance(outcomes.get("items"), list)
    finally:
        if session_id is not None:
            try:
                client.finish_session(session_id)
            finally:
                client.delete_recording(session_id)
