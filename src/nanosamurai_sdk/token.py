"""OAuth 2.0 client_credentials token acquisition for any OIDC provider.

Public API:
- `OIDCClientCredentialsTokenProvider`
- `KeycloakM2MTokenProvider` (former name, kept as an alias)

This is intentionally minimal:
- it finds the token endpoint and client authentication method through the
  issuer's OIDC discovery document
- caches tokens in-memory until shortly before expiry
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import httpx

from .errors import AuthError


@dataclass(frozen=True)
class Token:
    """Represents an access token + expiry.

    Attributes:
        access_token: Bearer token value.
        expires_at: Unix epoch seconds when the token expires.
    """

    access_token: str
    expires_at: float

    def is_valid(self, *, skew_s: float = 15.0) -> bool:
        """Return True when token is still valid considering a small skew."""

        return time.time() < (self.expires_at - skew_s)


DEFAULT_EXPIRES_IN_S = 60.0
"""Cache lifetime when a token response omits the optional `expires_in`."""


class OIDCClientCredentialsTokenProvider:
    """Acquire access tokens via client_credentials from any OIDC provider.

    Inputs:
        issuer: OIDC issuer, e.g. `https://auth.example/realms/<realm>`
        client_id: confidential client id
        client_secret: client secret
        timeout_s: HTTP timeout

    Notes:
        - Uses discovery to locate the token endpoint.
        - Sends the secret in the form body (`client_secret_post`) unless
          discovery lists only `client_secret_basic`, then uses HTTP Basic.
        - Caches the access token in-memory; without `expires_in` it caches
          for `DEFAULT_EXPIRES_IN_S`.
    """

    def __init__(
        self,
        *,
        issuer: str,
        client_id: str,
        client_secret: str,
        timeout_s: float = 10.0,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout_s = timeout_s
        self._token: Token | None = None
        self._token_endpoint: str | None = None
        self._basic_auth = False

    def _discovery_url(self) -> str:
        return f"{self._issuer}/.well-known/openid-configuration"

    def _get_token_endpoint(self) -> str:
        if self._token_endpoint:
            return self._token_endpoint

        try:
            with httpx.Client(timeout=self._timeout_s) as client:
                resp = client.get(self._discovery_url())
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:  # noqa: BLE001
            raise AuthError(f"Failed to load OIDC discovery from issuer={self._issuer}") from e

        token_endpoint = data.get("token_endpoint")
        if not isinstance(token_endpoint, str) or not token_endpoint:
            raise AuthError("OIDC discovery document missing token_endpoint")

        methods = data.get("token_endpoint_auth_methods_supported")
        self._basic_auth = (
            isinstance(methods, list)
            and "client_secret_basic" in methods
            and "client_secret_post" not in methods
        )
        self._token_endpoint = token_endpoint
        return token_endpoint

    def get_access_token(self) -> str:
        """Return a valid access token, refreshing if needed."""

        if self._token and self._token.is_valid():
            return self._token.access_token

        token_endpoint = self._get_token_endpoint()
        payload: dict[str, Any] = {"grant_type": "client_credentials"}
        auth: httpx.BasicAuth | None = None
        if self._basic_auth:
            auth = httpx.BasicAuth(self._client_id, self._client_secret)
        else:
            payload.update({"client_id": self._client_id, "client_secret": self._client_secret})

        try:
            with httpx.Client(timeout=self._timeout_s) as client:
                resp = client.post(
                    token_endpoint,
                    data=payload,
                    auth=auth,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:  # noqa: BLE001
            raise AuthError("Failed to acquire access token via client_credentials") from e

        access_token = data.get("access_token")
        expires_in = data.get("expires_in")

        if not isinstance(access_token, str) or not access_token:
            raise AuthError("Token response missing access_token")
        if expires_in is None:
            expires_in = DEFAULT_EXPIRES_IN_S
        if isinstance(expires_in, str) and expires_in.isdigit():
            expires_in = int(expires_in)
        if not isinstance(expires_in, (int, float)) or isinstance(expires_in, bool):
            raise AuthError("Token response has an invalid expires_in")

        self._token = Token(access_token=access_token, expires_at=time.time() + float(expires_in))
        return self._token.access_token


KeycloakM2MTokenProvider = OIDCClientCredentialsTokenProvider
"""Former name of `OIDCClientCredentialsTokenProvider`, kept for compatibility."""
