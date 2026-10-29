"""SDK error types.

We keep a small hierarchy so callers can catch SDK-level failures without
depending on underlying libraries.
"""


class NanosamuraiError(Exception):
    """Base error for all nanosamurai-sdk exceptions."""


class AuthError(NanosamuraiError):
    """Raised when acquiring or using an access token fails."""


class ApiError(NanosamuraiError):
    """Raised when the BFF REST API returns a non-success response."""

    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class WsError(NanosamuraiError):
    """Raised for websocket-related failures."""


SERVER_STOP_REASONS = {
    4403: "access-revoked",
    4408: "max-duration",
    4503: "access-unverified",
}
"""WebSocket close codes the BFF uses when it stops a session on purpose."""


class SessionStoppedError(WsError):
    """Raised when the BFF closed a session WebSocket on purpose.

    Attributes:
        close_code: 4403 (access revoked), 4408 (maximum duration reached) or
            4503 (access could not be verified).
        reason: ``access-revoked``, ``max-duration`` or ``access-unverified``.

    The access token is checked only when a socket opens, so token expiry
    does not stop a running session. Start a new session to continue.
    """

    def __init__(self, close_code: int, reason: str):
        super().__init__(f"The server stopped the session WebSocket ({reason}, code {close_code})")
        self.close_code = close_code
        self.reason = reason
