# nanosamurai-sdk

Python SDK + CLI for the **nanosamur.ai** API

This SDK targets the **machine-to-machine (M2M)** use-case:

- you create M2M credentials in the samuraibff UI (`/api-credentials`)
- you mint tokens via **nanosamurai's auth service** using `client_credentials`
- you call the BFF REST API and WebSockets with `Authorization: Bearer <token>`

## Install (dev)

### Virtual environment (recommended)

This repository does **not** commit a `.venv/` folder (it is intentionally in
`.gitignore`). If you clone the repo and `pip`/`python` commands seem to “not
work”, you most likely don’t have an activated virtual environment (or you’re
using a different Python interpreter than the one you installed into).

Create and activate a venv:

```bash
python -m venv .venv
```

Activate it:

- Windows (PowerShell):

```powershell
.\.venv\Scripts\Activate.ps1
```

  If PowerShell refuses to run scripts, either:
  - run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or
  - use the **cmd.exe** activation below.

- Windows (cmd.exe):

```bat
.venv\Scripts\activate.bat
```

- macOS / Linux:

```bash
source .venv/bin/activate
```

Then install:

```bash
python -m pip install -e ".[dev]"
```

## Install from a reviewed Git revision

Version **0.2.0** targets the BFF track API and pagination introduced in PR 149.
The SDK is not published to PyPI. Install this checkout with `pip install .`,
or pin a reviewed 0.2 commit after review. Do not install similarly named packages
from PyPI.

The existing consumer should keep its current **0.1 pin at `5b86461`** until its
upgrade is coordinated. The following command installs that older SDK:

```bash
python -m pip install "git+https://github.com/nanosamurai/nanosamurai-sdk.git@5b86461"
```

Pin deployments to a reviewed commit or release tag. Version 0.2 does not
negotiate the old flat realtime-tuning protocol. See [migration notes](#migration-to-02).

## Endpoint configuration

The SDK is self-hosting friendly. Hosted nanosamur.ai URLs are examples only;
set these values to your own deployment when running locally or on-prem.

CLI flags:

```bash
nanosamurai \
  --api-url http://127.0.0.1:8000 \
  --issuer http://127.0.0.1:8080/realms/nanosamurai \
  --client-id "$NANOSAMURAI_CLIENT_ID" \
  --client-secret "$NANOSAMURAI_CLIENT_SECRET" \
  recordings list
```

Environment variables:

The CLI (and examples) read configuration from:

- `NANOSAMURAI_API_URL` – base URL of samuraibff, e.g. `http://127.0.0.1:8000` or `https://platform.nanosamur.ai`
- `NANOSAMURAI_ISSUER` – OIDC realm issuer, e.g. `http://127.0.0.1:8080/realms/nanosamurai` or `https://auth.nanosamur.ai/realms/nanosamurai`
- `NANOSAMURAI_CLIENT_ID`
- `NANOSAMURAI_CLIENT_SECRET`

## CLI

If the `nanosamurai` script isn't on your PATH (common on Windows), you can
invoke the CLI via the module entrypoint:

```bash
python -m nanosamurai_sdk --help
```

Tip: when in doubt about which Python you are using (venv vs. global), prefer:

```bash
python -m pip --version
python -m nanosamurai_sdk --help
```

### Get an access token

```bash
nanosamurai token
```

Or:

```bash
python -m nanosamurai_sdk token
```

### List recordings

```bash
nanosamurai recordings list
nanosamurai recordings list --limit 20 --offset 20 --show-drafts --with-counts
```

### Get one recording (includes transcripts)

```bash
nanosamurai recordings get <session_id>
nanosamurai recordings get <session_id> --track-id whisperx
```

### Download recording audio (WAV)

```bash
nanosamurai recordings audio <session_id> --out out.wav
```

### Transcribe a WAV file (streams to WS)

```bash
nanosamurai transcribe wav path/to/audio.wav --lang en --sample-rate 16000
```

Examples using stream controls:

Realtime-only (disable refined + final outputs):

```bash
nanosamurai transcribe wav path/to/audio.wav \
  --lang en \
  --sample-rate 16000 \
  --realtime true \
  --refined false \
  --final false
```

Disable recording retention (keep final transcript, but do not keep audio for playback/download):

```bash
nanosamurai transcribe wav path/to/audio.wav \
  --lang en \
  --sample-rate 16000 \
  --final true \
  --store-recording false
```

Notes:
- for MVP, the CLI validates the WAV is **mono 16-bit PCM @ 16kHz**.
- the BFF expects PCM16LE frames on `/ws/audio`.

## Python SDK usage

### REST: list recordings

```python
import os
from nanosamurai_sdk import NanosamuraiClient


client = NanosamuraiClient(
    api_url=os.environ["NANOSAMURAI_API_URL"],
    issuer=os.environ["NANOSAMURAI_ISSUER"],
    client_id=os.environ["NANOSAMURAI_CLIENT_ID"],
    client_secret=os.environ["NANOSAMURAI_CLIENT_SECRET"],
)

items = client.list_recordings(limit=10, offset=0)
print("recordings", len(items))
page = client.list_recordings_page(limit=10, offset=10, show_drafts=True)
print("total", page.total, "drafts", page.drafts_count)
```

`list_recordings()` still returns a list. `list_recordings_page()` returns
`RecordingPage(items, total, drafts_count)`; `total` follows the draft filter.
Omit `show_drafts` to use the server default. Recording detail and its persisted
transcript dictionaries retain `track_id`, `model` and `provider_profile_id`.
Use `get_recording(session_id, track_id="whisperx")` to filter transcript history.

### REST: list workflows and webhooks

```python
import os
from nanosamurai_sdk import NanosamuraiClient


client = NanosamuraiClient(
    api_url=os.environ["NANOSAMURAI_API_URL"],
    issuer=os.environ["NANOSAMURAI_ISSUER"],
    client_id=os.environ["NANOSAMURAI_CLIENT_ID"],
    client_secret=os.environ["NANOSAMURAI_CLIENT_SECRET"],
)

workflows = client.list_workflows()
webhooks = client.list_webhooks()

print("workflows", len(workflows.get("items", [])))
print("webhooks", len(webhooks.get("items", [])))
```

### REST: create session with workflow/webhook overrides

```python
import os
from nanosamurai_sdk import NanosamuraiClient


client = NanosamuraiClient(
    api_url=os.environ["NANOSAMURAI_API_URL"],
    issuer=os.environ["NANOSAMURAI_ISSUER"],
    client_id=os.environ["NANOSAMURAI_CLIENT_ID"],
    client_secret=os.environ["NANOSAMURAI_CLIENT_SECRET"],
)

session_id = client.create_session(
    title="My session",
    webhook_overrides={
        "use_defaults": True,
        "webhook_ids": ["<uuid>"],
        "disable_event_types": ["transcript.refined.segment"],
    },
    workflow_overrides={
        "use_defaults": True,
        "workflow_ids": ["<uuid>"],
    },
)

print("session_id", session_id)
```

When audio capture ends, explicitly close the BFF session state machine:

```python
client.finish_session(session_id)
```

The SDK also supports both speaker-enrollment routes. Upload a WAV sample with
`client.create_speaker(label="Alice", sample_path="alice.wav")`, or enroll from
a stored recording with `client.create_speaker_from_recording(...)`.

### WebSockets: transcribe a WAV file (stream audio + receive events)

The BFF expects **PCM16LE mono @ 16kHz** frames sent as **binary** messages to
`/ws/audio`, while transcription events are received as JSON text messages from
`/ws/events`.

This example reuses the SDK's WAV helper which validates the format and yields
PCM frames in ~100ms chunks.

The sender paces PCM at the declared sample rate, including file input. Sending
a whole file as an immediate burst can overflow the BFF's bounded audio queue.
Allow at least the audio duration plus inference time in the completion deadline.

```python
import asyncio
import os

from nanosamurai_sdk import NanosamuraiClient
from nanosamurai_sdk.audio import wav_to_pcm_frames


async def main() -> None:
    client = NanosamuraiClient(
        api_url=os.environ["NANOSAMURAI_API_URL"],
        issuer=os.environ["NANOSAMURAI_ISSUER"],
        client_id=os.environ["NANOSAMURAI_CLIENT_ID"],
        client_secret=os.environ["NANOSAMURAI_CLIENT_SECRET"],
    )

    session_id = client.create_session()

    frames = wav_to_pcm_frames(
        "path/to/audio.wav",
        expected_sample_rate=16000,
        frame_bytes=3200,  # 100ms @ 16kHz mono PCM16
    )

    detail = await client.transcribe_pcm_until_complete(
        session_id=session_id,
        pcm_frames=frames,
        lang="en",  # or "de", etc.
        sample_rate=16000,
        # Optional stream controls:
        # realtime=True,
        # refined=True,
        # final=True,
        # store_recording=True,
        # refinement_window_sec=60.0,
        # realtime_tracks=["faster-whisper"],
        # refinement_tracks=["whisperx"],
        # final_tracks=["whisperx"],
        # realtime_settings={"faster-whisper": {"window_sec": 10, "overlap_sec": 0.5}},
        on_event=print,
    )
    print("persisted", detail["session"]["status"])


if __name__ == "__main__":
    asyncio.run(main())
```

## WebSockets API (realtime ASR)

`transcribe_pcm_until_complete()` is intended for finite recordings. It closes
audio, explicitly finishes the session and uses its persisted `stream_controls`
to resolve the admitted tracks. It waits for each realtime track's `stopped`
event, each selected final track's saved result, and each refinement track's
saved tail through the sent audio duration. Disabled stages need no output.
The first realtime `final=true` window and the session-wide final flag are
insufficient. `completion_timeout_s` covers connection, streaming and persistence,
even while events keep arriving. Cleanup has its own network timeouts.
The helper does not wait for workflows or webhook delivery. Use the lower-level
`transcribe_pcm()` iterator for open-ended/live capture and close or cancel that
iterator when capture stops. Its optional `event_idle_timeout_s` only limits
post-audio inactivity; it does not establish completion.

The REST API is documented in Swagger (`/docs`) but WebSockets are currently not
modeled in the OpenAPI spec. This section documents the realtime ASR WS
contract as implemented by **samuraibff**.

### Overview: two WebSocket connections

Realtime transcription uses two WebSockets:

1) **Events** (server → client):

```
GET /ws/events?session_id=<uuid>
```

Receives JSON text messages.

2) **Audio** (client → server):

```
GET /ws/audio?session_id=<uuid>&lang=<code>&sample_rate=16000[&...stream controls]
```

Sends raw audio frames as **binary** messages:
- encoding: **PCM16LE**
- channels: **mono**
- sample rate: typically **16kHz**

Auth: both endpoints require `Authorization: Bearer <token>` during the WS
upgrade (same token as for REST).

### Session lifecycle

For authenticated deployments, you must create a session first:

```
POST /api/sessions -> {"session_id": "..."}
```

Then connect `/ws/events` and `/ws/audio` with that `session_id`.

### Event types

All events share these common fields:

- `type`: one of `status`, `error`, `asr`, `refined`, `workflow_result`
- `session_id`: the session UUID
- `seq`: monotonic per-session sequence number
- `ts_ms`: event timestamp (epoch milliseconds)

Transcription and provider status events include `track`, `model` and
`provider_profile_id` where supplied by the service. The SDK preserves these
fields without collapsing results from different tracks.

#### status

Example:

```json
{
  "type": "status",
  "session_id": "2d5f4b0c-5f83-4b6e-9b6a-5e4d52f1b5c0",
  "seq": 1,
  "ts_ms": 1711800000000,
  "status": "connected",
  "detail": "events-ws"
}
```

#### asr: PARTIAL vs FINAL

Realtime ASR events have `type="asr"` and a `final` flag:

- `final=false` → **PARTIAL** hypothesis (replaceable)
- `final=true`  → **FINAL** for a completed window (locking)

The realtime service typically emits **multiple PARTIAL events** and then a
**FINAL event per window**.

PARTIAL example (`final=false`):

```json
{
  "type": "asr",
  "session_id": "2d5f4b0c-5f83-4b6e-9b6a-5e4d52f1b5c0",
  "seq": 12,
  "ts_ms": 1711800001234,
  "start_s": 10.0,
  "end_s": 15.0,
  "text": "hello wor",
  "lang": "en",
  "speaker": "SPEAKER_00",
  "final": false
}
```

FINAL example (`final=true`):

```json
{
  "type": "asr",
  "session_id": "2d5f4b0c-5f83-4b6e-9b6a-5e4d52f1b5c0",
  "seq": 13,
  "ts_ms": 1711800001890,
  "start_s": 10.0,
  "end_s": 15.0,
  "text": "hello world",
  "lang": "en",
  "speaker": "SPEAKER_00",
  "final": true
}
```

#### refined

Refined transcript segments (e.g. WhisperX) are pushed later over the same
`/ws/events` socket:

```json
{
  "type": "refined",
  "session_id": "2d5f4b0c-5f83-4b6e-9b6a-5e4d52f1b5c0",
  "seq": 200,
  "ts_ms": 1711800123456,
  "start_s": 10.0,
  "end_s": 15.0,
  "text": "Hello, world.",
  "lang": "en",
  "speaker": "SPEAKER_00"
}
```

#### error

```json
{
  "type": "error",
  "session_id": "2d5f4b0c-5f83-4b6e-9b6a-5e4d52f1b5c0",
  "seq": 42,
  "ts_ms": 1711800009999,
  "message": "invalid-audio-format",
  "detail": "expected pcm16le mono"
}
```

#### workflow_result

Workflow results are streamed to `/ws/events` when workflow-runner produces a
result for the current session. (These are also persisted and later visible via
`GET /api/recordings/:session_id` under `workflow_results_latest`.)

Example:

```json
{
  "type": "workflow_result",
  "session_id": "2d5f4b0c-5f83-4b6e-9b6a-5e4d52f1b5c0",
  "seq": 300,
  "ts_ms": 1711800123999,
  "workflow_id": "11111111-1111-1111-1111-111111111111",
  "workflow_name": "Summarize",
  "status": "succeeded",
  "render_markdown": "# Summary\n..."
}
```

The SDK provides a convenience filter:

```python
async for ev in client.iter_workflow_results(session_id=session_id):
    print(ev["workflow_id"], ev.get("status"))
```

### `/ws/audio` query parameters (stream controls)

`/ws/audio` accepts additional per-session controls via query parameters. These
are used by the web UI and are also available to SDK users.

You should treat these settings as **fixed for the whole stream** (do not
change them mid-connection).

#### Overview

| Parameter | Type | Default | Description |
|---|---:|---:|---|
| `session_id` | string (UUID) | required | Session id created via `POST /api/sessions`. |
| `lang` | string | `""` | ISO-639-1 language code (`en`, `cs`, ...). Empty means auto-detect. |
| `sample_rate` | int | `16000` | Input PCM sample rate (Hz). |
| `realtime` | bool | `true` | Produce realtime transcript events (`type="asr"`) on `/ws/events`. |
| `refined` | bool | `true` | Produce refined transcript events (`type="refined"`) on `/ws/events`. |
| `final` | bool | `true` | Produce final transcript artifacts for the session. |
| `store_recording` | bool | `true` | Keep the recording for later playback/download. Only relevant when `final=true`. |
| `refinement_window_sec` | float | server default | Tuning for refined transcript production. |
| `realtime_tracks` | comma-separated IDs | server default | Select realtime tracks; Python takes a list of strings. |
| `refinement_tracks` | comma-separated IDs | server default | Select refinement tracks. |
| `final_tracks` | comma-separated IDs | server default | Select final tracks. Multiple final tracks require recording retention. |
| `realtime_settings` | JSON object keyed by track ID | service defaults | Provider-specific settings, advertised by `/api/me`. |

Notes on defaults:
- When you **omit** an optional parameter, the server applies its default.
- For output selection (`realtime/refined/final`), the current server behavior
  defaults each to **`true`** when omitted.

#### Output selection: `realtime` / `refined` / `final`

These booleans control which transcript “layers” are produced for the stream.

Example (realtime only):

```
/ws/audio?session_id=<uuid>&lang=en&sample_rate=16000&realtime=true&refined=false&final=false
```

#### Recording retention: `store_recording`

Controls whether the session’s recording is retained for later playback / WAV
download.

```
/ws/audio?session_id=<uuid>&store_recording=false
```

#### Refinement tuning: `refinement_window_sec`

Optional refinement tuning knob.

```
/ws/audio?session_id=<uuid>&refinement_window_sec=60
```

#### Track selection and realtime settings

`client.me()` exposes `default_tracks`, `realtime_tracks`,
`realtime_track_capabilities` and `async_tracks`. Omitted selections use the
deployment defaults. Dev selects Faster Whisper medium for realtime and
WhisperX medium for refinement/final; it admits one realtime stream at a time.
Selecting a track does not enable a disabled stage. Explicit empty, duplicate
or malformed lists fail locally; the server checks configured availability.

```bash
nanosamurai transcribe wav path/to/audio.wav \
  --realtime-tracks faster-whisper --refinement-tracks whisperx --final-tracks whisperx \
  --realtime-settings '{"faster-whisper":{"partial_enable":false,"window_sec":10}}'
```

Read the selected provider's advertised setting types and limits before tuning.
For Faster Whisper, larger `window_sec` increases context and latency;
`emit_every_sec` controls partial-update frequency, and `overlap_sec` adds
overlap between windows. Other providers may expose different settings.

### Workflow trigger tracks

Transcript workflows require an explicit source track, including when created
through the CLI JSON payload. For example:

```python
trigger = {"type": "transcript.final.ready", "track_id": "whisperx"}
# Include this trigger in client.create_workflow({...}).
```

`transcript.refined.segment` also requires `track_id`. `recording.finished`
rejects a track. Updates that omit `trigger` retain the existing definition.

## Migration to 0.2

Default transcription calls still use the same Whisper services when track
arguments are omitted. `list_recordings()` retains its list return type.
The following deliberate API changes require review for existing callers:

| Previous Python / CLI option | Version 0.2 replacement |
|---|---|
| `rt_partial_enable` / `--rt-partial-enable` | `realtime_settings[track]["partial_enable"]` |
| `window_size` / `--window-size` | `realtime_settings[track]["window_sec"]` |
| `overlap` / `--overlap` | `realtime_settings[track]["overlap_sec"]` |
| `emit_every` / `--emit-every` | `realtime_settings[track]["emit_every_sec"]` |
| Finite helper `event_idle_timeout_s` / CLI `--event-idle-timeout-s` | `completion_timeout_s` / `--completion-timeout-s` bounds the whole operation |
| Transcript workflow without source track | Add `trigger.track_id` |

Do not pass removed flat options: the SDK rejects them rather than silently
ignoring tuning. Upgrade the deployment and client together; keep the existing
consumer pinned to `5b86461` until that review. There is no automatic fallback
to a pre-track server. The explicit `--stop-on-final` CLI option still stops at
the first final window and can truncate audio; omit it for complete recordings.

## Testing

The default suite is fully local and does not contact a deployment:

```bash
pytest -q
ruff check .
```

Opt-in live tests cover default tracks, explicit tracks/settings, disabled
refinement/final stages, capability discovery, pagination, OIDC, session creation, audio and
event WebSockets, realtime ASR, explicit session finish, persisted refined and
final transcripts, recording download, and read-only workflow/webhook APIs.
It requires a mono 16-bit PCM 16kHz WAV file:

```bash
NANOSAMURAI_RUN_LIVE_TESTS=1 \
NANOSAMURAI_TEST_WAV=path/to/non-sensitive-synthetic.wav \
pytest -q -m live tests/integration/test_live_transcription.py
```

The four standard `NANOSAMURAI_API_URL`, `NANOSAMURAI_ISSUER`,
`NANOSAMURAI_CLIENT_ID`, and `NANOSAMURAI_CLIENT_SECRET` variables must also be
set. The explicit `NANOSAMURAI_RUN_LIVE_TESTS=1` gate prevents accidental audio
uploads. Use only synthetic or otherwise approved test audio. The test deletes
each test's session and recording in a `finally` block. Test sessions explicitly
disable tenant workflow and webhook defaults, without changing tenant settings.
The BFF deployed with this rollout fixes `/api/me` for M2M identities with absent
optional claims and closes rejected WebSocket upgrade connections at the proxy.
