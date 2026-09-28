import httpx
import respx

from nanosamurai_sdk.client import NanosamuraiClient


def _client() -> NanosamuraiClient:
    client = NanosamuraiClient(
        api_url="https://platform.example",
        issuer="https://auth.example/realms/test",
        client_id="c",
        client_secret="s",
    )
    client.get_access_token = lambda: "tok"  # type: ignore[method-assign]
    return client


@respx.mock
def test_finish_session_calls_explicit_transition() -> None:
    client = _client()
    session_id = "11111111-1111-1111-1111-111111111111"
    route = respx.post(f"https://platform.example/api/sessions/{session_id}/finish").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "session_id": session_id, "status": "finished"},
        )
    )

    response = client.finish_session(session_id)

    assert route.called
    assert response["status"] == "finished"


@respx.mock
def test_rename_session_sends_title_patch() -> None:
    client = _client()
    session_id = "11111111-1111-1111-1111-111111111111"
    route = respx.patch(f"https://platform.example/api/sessions/{session_id}").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "session_id": session_id, "title": "Renamed session"},
        )
    )

    response = client.rename_session(session_id, title="Renamed session")

    assert route.called
    assert route.calls.last.request.content == b'{"title":"Renamed session"}'
    assert response["title"] == "Renamed session"


@respx.mock
def test_list_recordings_preserves_title() -> None:
    client = _client()
    respx.get("https://platform.example/api/recordings?limit=1&offset=0").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "total": 1,
                "drafts_count": 0,
                "items": [
                    {
                        "session_id": "11111111-1111-1111-1111-111111111111",
                        "session_key": "session-key",
                        "title": "Customer interview",
                        "status": "finished",
                        "started_at": None,
                        "ended_at": None,
                        "created_at": "2026-08-20 12:00:00",
                        "has_recording": False,
                        "has_final_transcript": True,
                        "recording": {
                            "created_at": None,
                            "duration_s": None,
                            "sample_rate": None,
                            "lang": None,
                        },
                    }
                ],
            },
        )
    )

    items = client.list_recordings(limit=1)

    assert len(items) == 1
    assert items[0].title == "Customer interview"


@respx.mock
def test_recording_detail_outcomes_and_delete_routes() -> None:
    client = _client()
    session_id = "11111111-1111-1111-1111-111111111111"
    detail_route = respx.get(f"https://platform.example/api/recordings/{session_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "session": {"id": session_id, "status": "finished"},
                "transcripts": {"refined": [], "final": []},
            },
        )
    )
    outcomes_route = respx.get(
        f"https://platform.example/api/sessions/{session_id}/webhook-delivery-outcomes"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "session_id": session_id, "items": []},
        )
    )
    delete_route = respx.delete(f"https://platform.example/api/recordings/{session_id}").mock(
        return_value=httpx.Response(200, json={"ok": True, "deleted": True})
    )

    assert client.get_recording(session_id)["session"]["status"] == "finished"
    assert client.list_webhook_delivery_outcomes(session_id)["items"] == []
    assert client.delete_recording(session_id)["deleted"] is True
    assert detail_route.called
    assert outcomes_route.called
    assert delete_route.called


@respx.mock
def test_pagination_counts_and_track_filter() -> None:
    client = _client()
    page_route = respx.get("https://platform.example/api/recordings",
                          params={"limit": 5, "offset": 10, "show_drafts": "true"}).mock(
        return_value=httpx.Response(200, json={"items": [], "total": 10, "drafts_count": 3}))
    detail_route = respx.get("https://platform.example/api/recordings/s",
                            params={"track_id": "whisperx"}).mock(
        return_value=httpx.Response(200, json={"transcripts": {"final": []}}))
    page = client.list_recordings_page(limit=5, offset=10, show_drafts=True)
    assert (page.items, page.total, page.drafts_count) == ([], 10, 3)
    assert client.get_recording("s", track_id="whisperx")["transcripts"]["final"] == []
    assert page_route.called and detail_route.called
