import pytest

from nanosamurai_sdk.client import NanosamuraiClient


@pytest.mark.asyncio
async def test_iter_workflow_results_filters_type(monkeypatch: pytest.MonkeyPatch) -> None:
    client = NanosamuraiClient(
        api_url="https://platform.example",
        issuer="https://auth.example/realms/test",
        client_id="c",
        client_secret="s",
    )

    async def _fake_iter_events(*, session_id: str):
        assert session_id == "sid"
        yield {"type": "status", "session_id": session_id}
        yield {"type": "workflow_result", "session_id": session_id, "workflow_id": "wf1"}
        yield {"type": "asr", "session_id": session_id}
        yield {"type": "workflow_result", "session_id": session_id, "workflow_id": "wf2"}

    monkeypatch.setattr(client, "iter_events", _fake_iter_events)

    out = []
    async for ev in client.iter_workflow_results(session_id="sid"):
        out.append(ev)

    assert [e["workflow_id"] for e in out] == ["wf1", "wf2"]


@pytest.mark.asyncio
async def test_iter_workflow_results_filters_by_workflow_id(monkeypatch: pytest.MonkeyPatch) -> None:
    client = NanosamuraiClient(
        api_url="https://platform.example",
        issuer="https://auth.example/realms/test",
        client_id="c",
        client_secret="s",
    )

    async def _fake_iter_events(*, session_id: str):
        yield {"type": "workflow_result", "session_id": session_id, "workflow_id": "wf1"}
        yield {"type": "workflow_result", "session_id": session_id, "workflow_id": "wf2"}

    monkeypatch.setattr(client, "iter_events", _fake_iter_events)

    out = []
    async for ev in client.iter_workflow_results(session_id="sid", workflow_id="wf2"):
        out.append(ev)

    assert [e["workflow_id"] for e in out] == ["wf2"]
