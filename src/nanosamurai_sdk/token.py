"""Keycloak M2M (client_credentials) token acquisition.

Public API:
- `KeycloakM2MTokenProvider`

This is intentionally minimal:
- it fetches tokens from Keycloak using the OIDC discovery document
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


class KeycloakM2MTokenProvider:
    """Acquire Keycloak access tokens via client_credentials.

    Inputs:
        issuer: Keycloak realm issuer, e.g. `https://auth.example/realms/<realm>`
        client_id: Keycloak confidential client id
        client_secret: Keycloak client secret
        timeout_s: HTTP timeout

    Notes:
        - Uses discovery to locate the token endpoint.
        - Caches the access token in-memory.
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

        self._token_endpoint = token_endpoint
        return token_endpoint

    def get_access_token(self) -> str:
        """Return a valid access token, refreshing if needed."""

        if self._token and self._token.is_valid():
            return self._token.access_token

        token_endpoint = self._get_token_endpoint()
        payload: dict[str, Any] = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }

        try:
            with httpx.Client(timeout=self._timeout_s) as client:
                resp = client.post(
                    token_endpoint,
                    data=payload,
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
        if not isinstance(expires_in, (int, float)):
            # Keycloak returns an int. Be permissive, but require numeric.
            raise AuthError("Token response missing expires_in")

        self._token = Token(access_token=access_token, expires_at=time.time() + float(expires_in))
        return self._token.access_token
