import time

import respx
import httpx

from nanosamurai_sdk.token import KeycloakM2MTokenProvider


@respx.mock
def test_token_provider_caches_token_until_expiry():
    issuer = "https://auth.example/realms/test"
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    token_endpoint = "https://auth.example/realms/test/protocol/openid-connect/token"

    respx.get(discovery_url).mock(
        return_value=httpx.Response(200, json={"issuer": issuer, "token_endpoint": token_endpoint})
    )

    calls = {"n": 0}

    def token_response(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"access_token": f"tok-{calls['n']}", "expires_in": 3600})

    respx.post(token_endpoint).mock(side_effect=token_response)

    tp = KeycloakM2MTokenProvider(issuer=issuer, client_id="c", client_secret="s")
    t1 = tp.get_access_token()
    t2 = tp.get_access_token()
    assert t1 == t2
    assert calls["n"] == 1


@respx.mock
def test_token_provider_refreshes_after_expiry():
    issuer = "https://auth.example/realms/test"
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    token_endpoint = "https://auth.example/realms/test/protocol/openid-connect/token"

    respx.get(discovery_url).mock(
        return_value=httpx.Response(200, json={"issuer": issuer, "token_endpoint": token_endpoint})
    )

    respx.post(token_endpoint).mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 1})
    )

    tp = KeycloakM2MTokenProvider(issuer=issuer, client_id="c", client_secret="s")
    _ = tp.get_access_token()
    time.sleep(1.2)
    # should fetch again
    respx.post(token_endpoint).mock(
        return_value=httpx.Response(200, json={"access_token": "tok2", "expires_in": 3600})
    )
    t2 = tp.get_access_token()
    assert t2 == "tok2"
