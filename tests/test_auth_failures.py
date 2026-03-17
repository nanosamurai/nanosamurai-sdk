import pytest
import respx
import httpx

from nanosamurai_sdk.client import NanosamuraiClient
from nanosamurai_sdk.errors import ApiError, AuthError


@respx.mock
def test_token_provider_raises_auth_error_on_401() -> None:
    issuer = "https://auth.example/realms/test"
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    token_endpoint = "https://auth.example/realms/test/protocol/openid-connect/token"

    respx.get(discovery_url).mock(
        return_value=httpx.Response(200, json={"issuer": issuer, "token_endpoint": token_endpoint})
    )
    respx.post(token_endpoint).mock(return_value=httpx.Response(401, json={"error": "invalid_client"}))

    client = NanosamuraiClient(
        api_url="https://platform.example",
        issuer=issuer,
        client_id="bad",
        client_secret="bad",
    )

    with pytest.raises(AuthError):
        _ = client.get_access_token()


@respx.mock
def test_rest_raises_api_error_on_401() -> None:
    issuer = "https://auth.example/realms/test"
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    token_endpoint = "https://auth.example/realms/test/protocol/openid-connect/token"

    respx.get(discovery_url).mock(
        return_value=httpx.Response(200, json={"issuer": issuer, "token_endpoint": token_endpoint})
    )
    respx.post(token_endpoint).mock(return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3600}))

    # BFF responds with 401 even though we sent a token (e.g. wrong audience / revoked)
    respx.post("https://platform.example/api/sessions").mock(return_value=httpx.Response(401, text="unauthorized"))

    client = NanosamuraiClient(
        api_url="https://platform.example",
        issuer=issuer,
        client_id="c",
        client_secret="s",
    )

    with pytest.raises(ApiError) as e:
        _ = client.create_session()

    assert e.value.status_code == 401
