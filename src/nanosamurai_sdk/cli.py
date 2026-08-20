"""Command line interface for nanosamurai-sdk.

Environment variables (preferred over flags for secrets):
  - NANOSAMURAI_API_URL
  - NANOSAMURAI_ISSUER
  - NANOSAMURAI_CLIENT_ID
  - NANOSAMURAI_CLIENT_SECRET

Subcommands:
  - token
  - recordings list
  - recordings get <session_id>
  - recordings audio <session_id> --out <path>
  - transcribe wav <path>
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
import os
import sys
from typing import Any

from .audio import wav_to_pcm_frames
from .client import NanosamuraiClient
from .errors import NanosamuraiError


def _parse_bool_or_none(v: str | None) -> bool | None:
    """Parse a tri-state boolean flag.

    - None or empty => None (omit from request, let server defaults apply)
    - "true"/"false" (case-insensitive) => bool
    """

    if v is None:
        return None
    s = str(v).strip().lower()
    if not s:
        return None
    if s in ("true", "1", "yes", "on"):
        return True
    if s in ("false", "0", "no", "off"):
        return False
    raise SystemExit(f"Invalid boolean value: {v!r} (expected true|false)")


def _env(name: str) -> str | None:
    v = os.environ.get(name)
    if v is None:
        return None
    v = v.strip()
    return v or None


def _build_client(args: argparse.Namespace) -> NanosamuraiClient:
    api_url = args.api_url or _env("NANOSAMURAI_API_URL")
    issuer = args.issuer or _env("NANOSAMURAI_ISSUER")
    client_id = args.client_id or _env("NANOSAMURAI_CLIENT_ID")
    client_secret = args.client_secret or _env("NANOSAMURAI_CLIENT_SECRET")

    missing = [
        n
        for n, v in [
            ("api_url", api_url),
            ("issuer", issuer),
            ("client_id", client_id),
            ("client_secret", client_secret),
        ]
        if not v
    ]
    if missing:
        raise SystemExit(
            "Missing configuration: "
            + ", ".join(missing)
            + "\nProvide flags or env vars: NANOSAMURAI_API_URL, NANOSAMURAI_ISSUER, NANOSAMURAI_CLIENT_ID, NANOSAMURAI_CLIENT_SECRET"
        )

    return NanosamuraiClient(
        api_url=api_url,
        issuer=issuer,
        client_id=client_id,
        client_secret=client_secret,
        timeout_s=args.timeout_s,
    )


def _print_json(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, indent=2, sort_keys=True))
    sys.stdout.write("\n")


def _cmd_recordings_audio(args: argparse.Namespace) -> int:
    client = _build_client(args)
    if not args.out:
        raise SystemExit("--out is required")
    client.download_recording_audio(args.session_id, args.out)
    return 0


async def _cmd_transcribe_wav(args: argparse.Namespace) -> int:
    client = _build_client(args)
    session_id = args.session_id or client.create_session()
    frames = wav_to_pcm_frames(args.path, expected_sample_rate=args.sample_rate)

    stream_options = {
        "session_id": session_id,
        "pcm_frames": frames,
        "lang": args.lang,
        "sample_rate": args.sample_rate,
        "realtime": _parse_bool_or_none(args.realtime),
        "refined": _parse_bool_or_none(args.refined),
        "final": _parse_bool_or_none(args.final),
        "store_recording": _parse_bool_or_none(args.store_recording),
        "refinement_window_sec": args.refinement_window_sec,
        "rt_partial_enable": _parse_bool_or_none(args.rt_partial_enable),
        "window_size": args.window_size,
        "overlap": args.overlap,
        "emit_every": args.emit_every,
    }

    if args.stop_on_final:
        stream = client.transcribe_pcm(**stream_options)
        try:
            async for event in stream:
                _print_json(event)
                if event.get("type") in ("refined", "asr") and bool(event.get("final")):
                    break
        finally:
            await stream.aclose()
            await asyncio.to_thread(client.finish_session, session_id)
        return 0

    await client.transcribe_pcm_until_complete(
        **stream_options,
        on_event=_print_json,
        event_idle_timeout_s=args.event_idle_timeout_s,
        completion_timeout_s=args.completion_timeout_s,
        completion_poll_interval_s=args.completion_poll_interval_s,
    )
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="nanosamurai", description="nanosamurai-sdk CLI")
    parser.add_argument("--api-url", help="BFF base URL (or env NANOSAMURAI_API_URL)")
    parser.add_argument("--issuer", help="Keycloak issuer (or env NANOSAMURAI_ISSUER)")
    parser.add_argument("--client-id", help="M2M client id (or env NANOSAMURAI_CLIENT_ID)")
    parser.add_argument("--client-secret", help="M2M client secret (or env NANOSAMURAI_CLIENT_SECRET)")
    parser.add_argument("--timeout-s", type=float, default=10.0, help="HTTP timeout (seconds)")

    sub = parser.add_subparsers(dest="cmd", required=True)

    # token
    p_token = sub.add_parser("token", help="Print an access token")
    p_token.set_defaults(_cmd="token")

    # recordings
    p_rec = sub.add_parser("recordings", help="Recordings commands")
    rec_sub = p_rec.add_subparsers(dest="recordings_cmd", required=True)
    p_rec_list = rec_sub.add_parser("list", help="List recordings")
    p_rec_list.add_argument("--limit", type=int, default=200)
    p_rec_list.add_argument("--offset", type=int, default=0)
    p_rec_list.set_defaults(_cmd="recordings_list")

    p_rec_get = rec_sub.add_parser("get", help="Get recording detail")
    p_rec_get.add_argument("session_id")
    p_rec_get.set_defaults(_cmd="recordings_get")

    p_rec_audio = rec_sub.add_parser("audio", help="Download recording audio (WAV)")
    p_rec_audio.add_argument("session_id")
    p_rec_audio.add_argument("--out", required=True, help="Output .wav path")
    p_rec_audio.set_defaults(_cmd="recordings_audio")

    # transcribe
    p_transcribe = sub.add_parser("transcribe", help="Transcription commands")
    t_sub = p_transcribe.add_subparsers(dest="transcribe_cmd", required=True)

    p_wav = t_sub.add_parser("wav", help="Transcribe a WAV file")
    p_wav.add_argument("path")
    p_wav.add_argument("--lang", default="")
    p_wav.add_argument("--sample-rate", type=int, default=16000)

    # Stream controls
    p_wav.add_argument(
        "--realtime",
        default=None,
        help="Enable realtime transcript output (true|false). Omit to use server default.",
    )
    p_wav.add_argument(
        "--refined",
        default=None,
        help="Enable refined transcript output (true|false). Omit to use server default.",
    )
    p_wav.add_argument(
        "--final",
        default=None,
        help="Enable final transcript output (true|false). Omit to use server default.",
    )
    p_wav.add_argument(
        "--store-recording",
        default=None,
        help="Keep the recording for later playback (true|false). Omit to use server default.",
    )
    p_wav.add_argument(
        "--refinement-window-sec",
        type=float,
        default=None,
        help="Refinement window size in seconds (maps to /ws/audio refinement_window_sec)",
    )
    p_wav.add_argument(
        "--window-size",
        type=float,
        default=None,
        help="Realtime ASR window size in seconds (maps to /ws/audio rt_window_sec)",
    )
    p_wav.add_argument(
        "--overlap",
        type=float,
        default=None,
        help="Realtime ASR window overlap in seconds (maps to /ws/audio rt_overlap_sec)",
    )
    p_wav.add_argument(
        "--emit-every",
        type=float,
        default=None,
        help="Emit PARTIAL ASR updates every N seconds (maps to /ws/audio rt_emit_every_sec)",
    )
    p_wav.add_argument(
        "--rt-partial-enable",
        default=None,
        help="Whether realtime ASR should emit PARTIAL hypotheses (true|false). Omit to use server default.",
    )
    p_wav.add_argument("--session-id", help="Use existing session id (default: create new)")
    p_wav.add_argument(
        "--stop-on-final",
        action="store_true",
        help=(
            "Stop when the first final ASR event is received, then explicitly finish the session. "
            "This can stop before all audio and asynchronous outputs are processed."
        ),
    )
    p_wav.add_argument(
        "--event-idle-timeout-s",
        type=float,
        default=15.0,
        help="Close the events socket after this idle period once audio is sent (default: 15)",
    )
    p_wav.add_argument(
        "--completion-timeout-s",
        type=float,
        default=180.0,
        help="Maximum wait for persisted final output (default: 180)",
    )
    p_wav.add_argument(
        "--completion-poll-interval-s",
        type=float,
        default=1.0,
        help="Recording-detail polling interval while waiting for completion (default: 1)",
    )
    p_wav.set_defaults(_cmd="transcribe_wav")

    args = parser.parse_args(argv)

    try:
        if args._cmd == "token":
            client = _build_client(args)
            sys.stdout.write(client.get_access_token() + "\n")
            return

        if args._cmd == "recordings_list":
            client = _build_client(args)
            items = client.list_recordings(limit=args.limit, offset=args.offset)
            _print_json([asdict(item) for item in items])
            return

        if args._cmd == "recordings_get":
            client = _build_client(args)
            _print_json(client.get_recording(args.session_id))
            return

        if args._cmd == "recordings_audio":
            raise SystemExit(_cmd_recordings_audio(args))

        if args._cmd == "transcribe_wav":
            raise SystemExit(asyncio.run(_cmd_transcribe_wav(args)))

        raise SystemExit(f"Unknown command: {args._cmd}")
    except NanosamuraiError as e:
        sys.stderr.write(f"ERROR: {e}\n")
        raise SystemExit(2) from e
