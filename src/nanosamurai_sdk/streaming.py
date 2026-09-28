"""Track selection and persisted completion checks for the current BFF API."""

from dataclasses import dataclass
import json
import math
from typing import Any


def track_ids(value: list[str] | None, name: str) -> list[str] | None:
    """Validate explicit track IDs; None leaves selection to server defaults."""
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty list of track IDs")
    if any(
        not isinstance(v, str) or not v or "," in v or any(c.isspace() for c in v) for v in value
    ):
        raise ValueError(f"{name} contains an invalid track ID")
    if len(set(value)) != len(value):
        raise ValueError(f"{name} must not contain duplicate track IDs")
    return list(value)


def audio_query(
    *,
    session_id: str,
    lang: str,
    sample_rate: int,
    realtime: bool | None,
    refined: bool | None,
    final: bool | None,
    store_recording: bool | None,
    refinement_window_sec: float | None,
    realtime_tracks: list[str] | None,
    refinement_tracks: list[str] | None,
    final_tracks: list[str] | None,
    realtime_settings: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    """Build track-aware query parameters without legacy flat realtime controls."""
    if type(sample_rate) is not int or sample_rate <= 0:
        raise ValueError("sample_rate must be a positive integer")
    query: dict[str, Any] = {"session_id": session_id, "lang": lang, "sample_rate": sample_rate}
    for name, enabled in [
        ("realtime", realtime),
        ("refined", refined),
        ("final", final),
        ("store_recording", store_recording),
    ]:
        if enabled is not None:
            if not isinstance(enabled, bool):
                raise TypeError(f"{name} must be a boolean or None")
            query[name] = str(enabled).lower()
    if refinement_window_sec is not None:
        if not math.isfinite(refinement_window_sec) or refinement_window_sec <= 0:
            raise ValueError("refinement_window_sec must be finite and positive")
        query["refinement_window_sec"] = float(refinement_window_sec)
    for name, selected in [
        ("realtime_tracks", realtime_tracks),
        ("refinement_tracks", refinement_tracks),
        ("final_tracks", final_tracks),
    ]:
        ids = track_ids(selected, name)
        if ids is not None:
            query[name] = ",".join(ids)
    if realtime_settings is not None:
        if not isinstance(realtime_settings, dict):
            raise TypeError("realtime_settings must map track IDs to settings objects")
        for track, settings in realtime_settings.items():
            track_ids([track], "realtime_settings")
            if not isinstance(settings, dict):
                raise TypeError("Each realtime_settings value must be a settings object")
        query["realtime_settings"] = json.dumps(
            realtime_settings, separators=(",", ":"), allow_nan=False
        )
    return query


@dataclass
class StreamState:
    """Private progress shared by the audio sender and finite completion helper."""

    audio_sent: bool = False
    audio_bytes: int = 0


def completion_ready(detail: dict[str, Any], stopped: set[str], duration_s: float) -> bool:
    """Require every admitted realtime, refinement and final track to finish.

    The persisted admission snapshot is authoritative for omitted defaults and
    disabled stages. A legacy session-wide final flag cannot prove completion.
    """
    session = detail.get("session", {})
    controls = session.get("stream_controls")
    if session.get("status") != "finished" or not isinstance(controls, dict):
        return False
    transcripts = detail.get("transcripts", {})
    for flag, key, rows in [
        ("realtime", "realtime_tracks", None),
        ("refined", "refinement_tracks", transcripts.get("refined", [])),
        ("final", "final_tracks", transcripts.get("final", [])),
    ]:
        if controls.get(flag) is False:
            continue
        selected = controls.get(key)
        if controls.get(flag) is not True or not isinstance(selected, list) or not selected:
            return False
        if rows is None:
            completed = stopped
        elif flag == "final":
            completed = {r.get("track_id") for r in rows}
        else:
            completed = {
                r.get("track_id")
                for r in rows
                if isinstance(r.get("segment_end_s"), (int, float))
                and r["segment_end_s"] + 0.001 >= duration_s
            }
        if not set(selected).issubset(completed):
            return False
    return True
