"""Audio helpers.

Currently we only support a basic CLI-friendly path:
- load a WAV file
- validate it is PCM16LE mono
- return PCM frames for streaming

We intentionally do not include microphone capture libs in the SDK.
"""

from __future__ import annotations

import wave
from typing import Iterable

from .errors import NanosamuraiError


class AudioFormatError(NanosamuraiError):
    """Raised when provided audio input is not compatible with the BFF."""


def wav_to_pcm_frames(
    path: str,
    *,
    frame_bytes: int = 3200,
    expected_sample_rate: int = 16000,
) -> Iterable[bytes]:
    """Read a WAV file and yield PCM16LE frames.

    Inputs:
        path: filesystem path to a WAV file.
        frame_bytes: chunk size in bytes to yield (default 3200 == 100ms @ 16kHz mono PCM16).
        expected_sample_rate: default 16000.

    Returns:
        iterable of PCM frames (bytes).

    Raises:
        AudioFormatError if the WAV file is not compatible.
    """

    wf = wave.open(path, "rb")
    with wf:
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        comptype = wf.getcomptype()

        if comptype != "NONE":
            raise AudioFormatError(f"WAV must be uncompressed PCM (got comptype={comptype})")
        if nchannels != 1:
            raise AudioFormatError(f"WAV must be mono (got channels={nchannels})")
        if sampwidth != 2:
            raise AudioFormatError(f"WAV must be 16-bit PCM (got sampwidth={sampwidth})")
        if framerate != expected_sample_rate:
            raise AudioFormatError(
                f"WAV sample_rate must be {expected_sample_rate} (got {framerate}). "
                "Resample before using the CLI."
            )

        while True:
            chunk = wf.readframes(frame_bytes // 2)  # 2 bytes per sample
            if not chunk:
                break
            yield chunk
