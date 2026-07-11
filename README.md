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

## Install (normal)

```bash
pip install nanosamurai-sdk
```

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
```

### Get one recording (includes transcripts)

```bash
nanosamurai recordings get <session_id>
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
```

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

### WebSockets: transcribe a WAV file (stream audio + receive events)

The BFF expects **PCM16LE mono @ 16kHz** frames sent as **binary** messages to
`/ws/audio`, while transcription events are received as JSON text messages from
`/ws/events`.

This example reuses the SDK's WAV helper which validates the format and yields
PCM frames in ~100ms chunks.

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

    async for evt in client.transcribe_pcm(
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
        # rt_partial_enable=True,
        # rt_window_sec=5.0,
        # rt_overlap_sec=0.5,
        # rt_emit_every_sec=1.0,
    ):
        # evt is a dict, typically with keys: type, session_id, seq, ts_ms, ...
        print(evt)

        # optional: stop on first final ASR message.
        # NOTE: the realtime ASR service emits multiple PARTIAL events and then
        # a FINAL event *per window*; this will therefore usually stop before
        # the whole audio is fully transcribed.
        if evt.get("type") in ("refined", "asr") and evt.get("final") is True:
            break


if __name__ == "__main__":
    asyncio.run(main())
```

## WebSockets API (realtime ASR)

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
| `rt_partial_enable` | bool | server default | If `false`, realtime PARTIAL hypotheses are suppressed (FINALs still emit). |
| `rt_window_sec` | float | server default | Realtime ASR window size in seconds. |
| `rt_overlap_sec` | float | server default | Realtime ASR overlap in seconds. |
| `rt_emit_every_sec` | float | server default | Emit PARTIAL realtime updates every N seconds. |

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

#### Realtime tuning: `rt_partial_enable` / `rt_window_sec` / `rt_overlap_sec` / `rt_emit_every_sec`

These parameters tune realtime ASR behavior.

Example:

```
/ws/audio?session_id=<uuid>&lang=en&sample_rate=16000&rt_partial_enable=true&rt_window_sec=5.0&rt_overlap_sec=0.5&rt_emit_every_sec=1.0
```

Note: `rt_emit_every_sec` may have a server-side minimum (to avoid excessive
update frequency).

Tradeoffs:

- `rt_window_sec`:
  - larger → more context / typically better stability, but higher latency
  - smaller → lower latency, but less context (more unstable hypotheses)
- `rt_emit_every_sec`:
  - smaller → more frequent PARTIAL updates (more “live”), but more WS traffic
  - larger → fewer updates, but UI feels less responsive
- `rt_overlap_sec`:
  - can reduce word-boundary errors between windows
  - increases duplicated audio processing (more compute)
