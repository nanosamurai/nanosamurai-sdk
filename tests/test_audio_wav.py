import io
import wave

import pytest

from nanosamurai_sdk.audio import AudioFormatError, wav_to_pcm_frames


def _make_wav_bytes(*, channels: int = 1, sampwidth: int = 2, framerate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(framerate)
        wf.writeframes(b"\x00\x00" * 160)  # 10ms
    return buf.getvalue()


def test_wav_to_pcm_frames_rejects_stereo(tmp_path):
    p = tmp_path / "stereo.wav"
    p.write_bytes(_make_wav_bytes(channels=2))
    with pytest.raises(AudioFormatError):
        list(wav_to_pcm_frames(str(p)))


def test_wav_to_pcm_frames_ok(tmp_path):
    p = tmp_path / "mono.wav"
    p.write_bytes(_make_wav_bytes())
    frames = list(wav_to_pcm_frames(str(p), frame_bytes=40))
    assert frames
    assert all(isinstance(f, (bytes, bytearray)) for f in frames)
