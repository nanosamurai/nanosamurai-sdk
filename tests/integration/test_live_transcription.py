from datetime import datetime, timezone
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
@pytest.mark.parametrize("selection", ["defaults", "explicit", "realtime-only"])
async def test_live_transcription_reaches_persisted_final_output(selection) -> None:
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
        me = client.me()
        assert me["authenticated"]
        defaults = me["default_tracks"]
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        session_id = client.create_session(
            title=f"SDK live integration {timestamp}",
            webhook_overrides={"use_defaults": False, "webhook_ids": []},
            workflow_overrides={"use_defaults": False, "workflow_ids": []},
        )
        renamed_title = f"SDK live integration running {timestamp}"
        rename_response = client.rename_session(session_id, title=renamed_title)
        assert rename_response["title"] == renamed_title

        options = {}
        if selection != "defaults":
            options = {
                "realtime_tracks": [defaults["realtime"]],
                "refinement_tracks": [defaults["refined"]],
                "final_tracks": [defaults["final"]],
                "realtime_settings": {defaults["realtime"]: {"partial_enable": False}},
            }
        if selection == "realtime-only":
            options.update(refined=False, final=False, store_recording=False)
        detail = await client.transcribe_pcm_until_complete(
            session_id=session_id,
            pcm_frames=wav_to_pcm_frames(str(wav_path)),
            lang=os.environ.get("NANOSAMURAI_TEST_LANG", "en"),
            sample_rate=16000,
            on_event=events.append,
            completion_timeout_s=float(os.environ.get("NANOSAMURAI_TEST_COMPLETION_S", "240")),
            **options,
        )

        session = detail["session"]
        transcripts = detail["transcripts"]
        assert session["status"] == "finished"
        assert session["title"] == renamed_title
        assert any(
            event.get("type") == "asr" and event.get("track") == defaults["realtime"]
            for event in events
        )
        assert any(
            event.get("type") == "status"
            and event.get("status") == "stopped"
            and event.get("track") == defaults["realtime"]
            for event in events
        )
        controls = session["stream_controls"]
        assert controls["realtime_tracks"] == [defaults["realtime"]]
        if selection != "defaults":
            assert controls["realtime_settings"] == options["realtime_settings"]
        if selection == "realtime-only":
            assert not controls["refined"] and not controls["final"]
            assert not transcripts["refined"] and not transcripts["final"]
            assert not session["has_recording"]
        else:
            assert session["has_recording"] is True
            assert session["has_final_transcript"] is True
            assert {row["track_id"] for row in transcripts["refined"]} == {defaults["refined"]}
            assert {row["track_id"] for row in transcripts["final"]} == {defaults["final"]}
            filtered = client.get_recording(session_id, track_id=defaults["final"])
            assert filtered["transcripts"]["final"] == transcripts["final"]

            audio_prefix = client.get_recording_audio_bytes(session_id, range_start=0, range_end=43)
            assert len(audio_prefix) == 44
            assert audio_prefix.startswith(b"RIFF")
        page = client.list_recordings_page(limit=2, show_drafts=True)
        assert page.total >= 1 and page.drafts_count >= 0
        assert len(page.items) <= 2

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
