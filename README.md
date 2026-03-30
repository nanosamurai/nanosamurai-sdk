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

## Environment variables

The CLI (and examples) read configuration from:

- `NANOSAMURAI_API_URL` – base URL of samuraibff (e.g. `https://platform.nanosamur.ai`)
- `NANOSAMURAI_ISSUER` – nanosamurai realm issuer (e.g. `https://auth.nanosamur.ai/realms/nanosamurai`)
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
