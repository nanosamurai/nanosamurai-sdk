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
def test_list_recordings_preserves_title() -> None:
    client = _client()
    respx.get("https://platform.example/api/recordings?limit=1&offset=0").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "tenant_id": "00000000-0000-0000-0000-000000000000",
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
