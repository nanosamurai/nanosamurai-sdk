from __future__ import annotations

from nanosamurai_sdk import cli


class FakeClient:
    calls: list[dict[str, object]] = []

    def __init__(
        self,
        *,
        api_url: str,
        issuer: str,
        client_id: str,
        client_secret: str,
        timeout_s: float = 10.0,
    ) -> None:
        self.calls.append(
            {
                "api_url": api_url,
                "issuer": issuer,
                "client_id": client_id,
                "client_secret": client_secret,
                "timeout_s": timeout_s,
            }
        )

    def get_access_token(self) -> str:
        return "token"


def test_cli_uses_endpoint_flags(monkeypatch, capsys) -> None:
    FakeClient.calls = []
    monkeypatch.setattr(cli, "NanosamuraiClient", FakeClient)

    cli.main(
        [
            "--api-url",
            "http://127.0.0.1:8000",
            "--issuer",
            "http://127.0.0.1:8080/realms/nanosamurai",
            "--client-id",
            "local-client",
            "--client-secret",
            "local-secret",
            "token",
        ]
    )

    assert FakeClient.calls == [
        {
            "api_url": "http://127.0.0.1:8000",
            "issuer": "http://127.0.0.1:8080/realms/nanosamurai",
            "client_id": "local-client",
            "client_secret": "local-secret",
            "timeout_s": 10.0,
        }
    ]
    assert capsys.readouterr().out == "token\n"


def test_cli_uses_endpoint_env_vars(monkeypatch, capsys) -> None:
    FakeClient.calls = []
    monkeypatch.setattr(cli, "NanosamuraiClient", FakeClient)
    monkeypatch.setenv("NANOSAMURAI_API_URL", "http://localhost:8000")
    monkeypatch.setenv("NANOSAMURAI_ISSUER", "http://localhost:8080/realms/local")
    monkeypatch.setenv("NANOSAMURAI_CLIENT_ID", "env-client")
    monkeypatch.setenv("NANOSAMURAI_CLIENT_SECRET", "env-secret")

    cli.main(["token"])

    assert FakeClient.calls == [
        {
            "api_url": "http://localhost:8000",
            "issuer": "http://localhost:8080/realms/local",
            "client_id": "env-client",
            "client_secret": "env-secret",
            "timeout_s": 10.0,
        }
    ]
    assert capsys.readouterr().out == "token\n"
