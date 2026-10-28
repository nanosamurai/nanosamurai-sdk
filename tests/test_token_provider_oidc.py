import base64

import httpx
import pytest
import respx

from nanosamurai_sdk.errors import AuthError
from nanosamurai_sdk.token import KeycloakM2MTokenProvider, OIDCClientCredentialsTokenProvider

ISSUER = "https://id.example/oauth2/default"
TOKEN_ENDPOINT = "https://id.example/oauth2/default/v1/token"


def _discovery(**extra):
    return httpx.Response(200, json={"issuer": ISSUER, "token_endpoint": TOKEN_ENDPOINT, **extra})


def _provider():
    return OIDCClientCredentialsTokenProvider(issuer=ISSUER, client_id="cid", client_secret="sec")


@respx.mock
def test_uses_http_basic_when_the_provider_supports_only_basic() -> None:
    respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
        return_value=_discovery(token_endpoint_auth_methods_supported=["client_secret_basic"])
    )
    route = respx.post(TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
    )

    assert _provider().get_access_token() == "tok"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"cid:sec").decode()
    assert b"client_secret" not in request.content


@respx.mock
def test_posts_the_secret_by_default() -> None:
    respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
        return_value=_discovery(token_endpoint_auth_methods_supported=["client_secret_basic", "client_secret_post"])
    )
    route = respx.post(TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
    )

    assert _provider().get_access_token() == "tok"
    request = route.calls.last.request
    assert "Authorization" not in request.headers
    assert b"client_secret=sec" in request.content


@respx.mock
def test_accepts_a_token_response_without_expires_in() -> None:
    respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(return_value=_discovery())
    route = respx.post(TOKEN_ENDPOINT).mock(return_value=httpx.Response(200, json={"access_token": "tok"}))

    provider = _provider()
    assert provider.get_access_token() == "tok"
    assert provider.get_access_token() == "tok"
    assert route.call_count == 1


@respx.mock
def test_rejects_an_invalid_expires_in() -> None:
    respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(return_value=_discovery())
    respx.post(TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": "soon"})
    )

    with pytest.raises(AuthError):
        _provider().get_access_token()


def test_former_name_still_works() -> None:
    assert KeycloakM2MTokenProvider is OIDCClientCredentialsTokenProvider
