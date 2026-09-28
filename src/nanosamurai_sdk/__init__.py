"""nanosamurai_sdk

Python SDK for the nanosamur.ai BFF (samuraibff).

This package is intentionally small and focuses on the M2M (client_credentials)
use-case for 3rd party integrations.
"""

from .client import NanosamuraiClient, RecordingItem, RecordingPage

__all__ = ["NanosamuraiClient", "RecordingItem", "RecordingPage"]
