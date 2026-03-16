# nanosamurai-sdk

Python SDK + CLI for the **nanosamur.ai** API (samuraibff).

This SDK targets the **machine-to-machine (M2M)** use-case:

- you create M2M credentials in the samuraibff UI (`/api-credentials`)
- you mint tokens via **Keycloak** using `client_credentials`
- you call the BFF REST API and WebSockets with `Authorization: Bearer <token>`

## Install (dev)

```bash
pip install -e .[dev]
```

## Environment variables

The CLI (and examples) read configuration from:

- `NANOSAMURAI_API_URL` – base URL of samuraibff (e.g. `http://127.0.0.1:8000`)
- `NANOSAMURAI_ISSUER` – Keycloak realm issuer (e.g. `https://auth.nanosamur.ai/realms/nanosamurai`)
- `NANOSAMURAI_CLIENT_ID`
- `NANOSAMURAI_CLIENT_SECRET`

## CLI

### Get an access token

```bash
nanosamurai token
```

### List recordings

```bash
nanosamurai recordings list
```

### Get one recording (includes transcripts)

```bash
nanosamurai recordings get <session_id>
```

### Transcribe a WAV file (streams to WS)

```bash
nanosamurai transcribe wav path/to/audio.wav --lang en --sample-rate 16000
```

Notes:
- for MVP, the CLI validates the WAV is **mono 16-bit PCM @ 16kHz**.
- the BFF expects PCM16LE frames on `/ws/audio`.

## Python usage

```python
import asyncio
from nanosamurai_sdk import NanosamuraiClient


async def main():
    client = NanosamuraiClient(
        api_url="http://127.0.0.1:8000",
        issuer="https://auth.nanosamur.ai/realms/nanosamurai",
        client_id="...",
        client_secret="...",
    )

    session_id = client.create_session()

    # pcm_frames must yield bytes of PCM16LE mono
    pcm_frames = [b"\x00\x00" * 1600]

    async for evt in client.transcribe_pcm(
        session_id=session_id,
        pcm_frames=pcm_frames,
        lang="en",
        sample_rate=16000,
    ):
        print(evt)


asyncio.run(main())
```
