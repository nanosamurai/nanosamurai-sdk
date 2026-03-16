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
