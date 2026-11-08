from types import SimpleNamespace

import httpx
import pytest
import respx

from nanosamurai_sdk import cli
from nanosamurai_sdk.client import NanosamuraiClient
from nanosamurai_sdk.errors import ApiError

SESSION_ID = "11111111-1111-1111-1111-111111111111"
UPLOAD_URL = "https://platform.example/api/sessions/upload"
DETAIL_URL = f"https://platform.example/api/recordings/{SESSION_ID}"


def _client() -> NanosamuraiClient:
    client = NanosamuraiClient(
        api_url="https://platform.example",
        issuer="https://auth.example/realms/test",
        client_id="c",
        client_secret="s",
    )
    client.get_access_token = lambda: "tok"  # type: ignore[method-assign]
    return client


def _detail(final_rows: list[dict]) -> dict:
    return {
        "session": {
            "status": "finished",
            "stream_controls": {
                "realtime": False,
                "refined": False,
                "final": True,
                "final_tracks": ["whisperx", "qwen"],
            },
        },
        "transcripts": {"final": final_rows, "refined": []},
    }


@respx.mock
def test_upload_file_sends_multipart_without_the_local_file_name(tmp_path) -> None:
    media = tmp_path / "secret-interview-name.m4a"
    media.write_bytes(b"\x00\x00\x00\x1cftypM4A audio")
    route = respx.post(UPLOAD_URL).mock(
        return_value=httpx.Response(200, json={"session_id": SESSION_ID, "title": "Interview"})
    )

    result = _client().upload_file(
        media, title="Interview", lang="en", final_tracks=["whisperx", "qwen"], store_recording=True
    )

    assert result == {"session_id": SESSION_ID, "title": "Interview"}
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer tok"
    assert request.headers["content-type"].startswith("multipart/form-data")
    body = request.content
    assert b"ftypM4A audio" in body
    for field, value in [
        (b"title", b"Interview"),
        (b"lang", b"en"),
        (b"final_tracks", b"whisperx,qwen"),
        (b"store_recording", b"true"),
    ]:
        assert b'name="' + field + b'"\r\n\r\n' + value in body
    assert b"secret-interview-name" not in body


@respx.mock
def test_upload_file_omits_unset_fields(tmp_path) -> None:
    media = tmp_path / "a.wav"
    media.write_bytes(b"RIFF....WAVE")
    route = respx.post(UPLOAD_URL).mock(
        return_value=httpx.Response(200, json={"session_id": SESSION_ID, "title": "Upload"})
    )

    _client().upload_file(media)

    body = route.calls.last.request.content
    assert b'name="file"' in body
    assert b'name="title"' not in body and b'name="lang"' not in body


@pytest.mark.parametrize("status,message", [(413, "file-too-large"), (415, "unsupported-media-type")])
@respx.mock
def test_upload_file_reports_rejections(tmp_path, status, message) -> None:
    media = tmp_path / "a.bin"
    media.write_bytes(b"x")
    respx.post(UPLOAD_URL).mock(
        return_value=httpx.Response(status, json={"ok": False, "message": message})
    )

    with pytest.raises(ApiError) as error:
        _client().upload_file(media)

    assert error.value.status_code == status
    assert message in error.value.body


def test_upload_file_validates_track_ids(tmp_path) -> None:
    media = tmp_path / "a.wav"
    media.write_bytes(b"x")
    with pytest.raises(ValueError):
        _client().upload_file(media, final_tracks=["a,b"])


@respx.mock
def test_wait_for_final_transcripts_waits_for_every_selected_track(monkeypatch) -> None:
    monkeypatch.setattr("nanosamurai_sdk.client.time.sleep", lambda _s: None)
    route = respx.get(DETAIL_URL).mock(
        side_effect=[
            httpx.Response(503, json={"ok": False}),
            httpx.Response(200, json=_detail([{"track_id": "whisperx"}])),
            httpx.Response(200, json=_detail([{"track_id": "whisperx"}, {"track_id": "qwen"}])),
        ]
    )

    detail = _client().wait_for_final_transcripts(SESSION_ID, poll_interval_s=0.01)

    assert route.call_count == 3
    assert {r["track_id"] for r in detail["transcripts"]["final"]} == {"whisperx", "qwen"}


@respx.mock
def test_wait_for_final_transcripts_times_out(monkeypatch) -> None:
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr("nanosamurai_sdk.client.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("nanosamurai_sdk.client.time.sleep", lambda _s: None)
    respx.get(DETAIL_URL).mock(return_value=httpx.Response(200, json=_detail([])))

    with pytest.raises(ApiError, match="Timed out"):
        _client().wait_for_final_transcripts(SESSION_ID, timeout_s=30, poll_interval_s=5)


@respx.mock
def test_wait_for_final_transcripts_stops_when_the_session_fails(monkeypatch) -> None:
    monkeypatch.setattr("nanosamurai_sdk.client.time.sleep", lambda _s: None)
    failed = _detail([])
    failed["session"]["status"] = "failed"
    route = respx.get(DETAIL_URL).mock(
        side_effect=[httpx.Response(200, json=_detail([])), httpx.Response(200, json=failed)]
    )

    with pytest.raises(ApiError, match="session failed"):
        _client().wait_for_final_transcripts(SESSION_ID, poll_interval_s=0.01)
    assert route.call_count == 2


def _file_args(**overrides) -> SimpleNamespace:
    values = dict(
        path="interview.mp3",
        title=None,
        lang="en",
        final_tracks=["whisperx"],
        store_recording="false",
        no_wait=False,
        upload_timeout_s=600.0,
        wait_timeout_s=60.0,
        poll_interval_s=1.0,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("no_wait", [False, True])
def test_cli_transcribe_file(monkeypatch, capsys, no_wait) -> None:
    calls: list = []

    class _Client:
        def upload_file(self, path, **kwargs):
            calls.append(("upload", path, kwargs))
            return {"session_id": SESSION_ID, "title": "Upload"}

        def wait_for_final_transcripts(self, session_id, **kwargs):
            calls.append(("wait", session_id, kwargs))
            return {"transcripts": {"final": [{"track_id": "whisperx", "full_text": "hello"}]}}

    monkeypatch.setattr(cli, "_build_client", lambda _args: _Client())

    assert cli._cmd_transcribe_file(_file_args(no_wait=no_wait)) == 0

    upload = calls[0]
    assert upload[1] == "interview.mp3"
    assert upload[2]["store_recording"] is False and upload[2]["final_tracks"] == ["whisperx"]
    out = capsys.readouterr().out
    if no_wait:
        assert len(calls) == 1 and SESSION_ID in out
    else:
        assert calls[1] == ("wait", SESSION_ID, {"timeout_s": 60.0, "poll_interval_s": 1.0})
        assert '"full_text": "hello"' in out


def test_cli_parses_transcribe_file(monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(cli, "_cmd_transcribe_file", lambda args: seen.setdefault("args", args) and 0)

    with pytest.raises(SystemExit):
        cli.main(["transcribe", "file", "talk.webm", "--final-tracks", "whisperx,qwen", "--no-wait"])

    args = seen["args"]
    assert args.path == "talk.webm" and args.final_tracks == ["whisperx", "qwen"] and args.no_wait
