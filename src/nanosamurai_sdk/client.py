"""High-level nanosamurai client.

This client covers the endpoints that make sense for 3rd parties:

- REST:
  - GET /api/me
  - POST /api/sessions (supports workflow/webhook overrides)
  - PATCH /api/sessions/:session_id
  - GET /api/recordings
  - GET /api/recordings/:session_id
  - GET /api/recordings/:session_id/audio
  - DELETE /api/recordings/:session_id
  - GET /api/sessions/:session_id/webhook-delivery-outcomes
  - Speakers: /api/speakers, /api/speaker-enrollment/from-recording
  - API credentials: /api/api-credentials
  - Webhooks: /api/webhooks (+ defaults)
  - Workflows: /api/workflows (+ defaults)

- WebSockets:
  - /ws/events (JSON text messages)
  - /ws/audio (binary PCM16LE frames)

Auth model:
- Uses OAuth2 client_credentials against Keycloak to mint an access token.
- Sends `Authorization: Bearer <token>` to REST + WS.

All WS methods are async.
"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import json
from pathlib import Path
from typing import Any, AsyncIterator, Iterable
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import httpx
import websockets

from .errors import ApiError, WsError
from .token import KeycloakM2MTokenProvider


@dataclass(frozen=True)
class RecordingItem:
    """A single item from `GET /api/recordings`."""

    session_id: str
    session_key: str | None
    title: str | None
    status: str | None
    started_at: str | None
    ended_at: str | None
    created_at: str | None
    has_recording: bool | None
    has_final_transcript: bool | None
    recording: "RecordingInfo | None" = None


@dataclass(frozen=True)
class RecordingInfo:
    """Recording metadata attached to a RecordingItem.

    This corresponds to the nested `recording` object returned by the BFF.

    Fields are best-effort and may be null/absent depending on the persistence
    state.
    """

    created_at: str | None
    duration_s: float | None
    sample_rate: int | None
    lang: str | None


class NanosamuraiClient:
    """SDK client for samuraibff.

    Inputs:
        api_url: Base URL of the BFF (e.g. `http://127.0.0.1:8000` or `https://bff...`).
        issuer: Keycloak realm issuer (for discovery).
        client_id: M2M client id.
        client_secret: M2M client secret.
        timeout_s: REST timeout.
    """

    def __init__(
        self,
        *,
        api_url: str,
        issuer: str,
        client_id: str,
        client_secret: str,
        timeout_s: float = 10.0,
    ) -> None:
        self._api_url = api_url.rstrip("/") + "/"
        self._timeout_s = timeout_s
        self._token_provider = KeycloakM2MTokenProvider(
            issuer=issuer,
            client_id=client_id,
            client_secret=client_secret,
            timeout_s=timeout_s,
        )

    # -----------------
    # Auth
    # -----------------

    def get_access_token(self) -> str:
        """Return a valid access token (cached in-memory)."""

        return self._token_provider.get_access_token()

    def _authz_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_access_token()}"}

    # -----------------
    # REST helpers
    # -----------------

    def _rest_url(self, path: str) -> str:
        return urljoin(self._api_url, path.lstrip("/"))

    def _rest_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call a REST endpoint and return a parsed JSON object.

        Inputs:
            method: HTTP method (GET/POST/PUT/PATCH/DELETE)
            path: Absolute path (e.g. "/api/workflows")
            json_body: Optional JSON body dict.
            params: Optional query parameters.

        Returns:
            Parsed JSON object as a dict.

        Raises:
            ApiError on non-2xx or invalid JSON object response.
        """

        url = self._rest_url(path)
        with httpx.Client(timeout=self._timeout_s) as client:
            resp = client.request(
                method.upper(),
                url,
                headers=self._authz_headers(),
                json=json_body,
                params=params,
            )
        if resp.status_code // 100 != 2:
            raise ApiError(
                f"REST call failed: {method.upper()} {path}",
                status_code=resp.status_code,
                body=resp.text,
            )
        data = resp.json()
        if not isinstance(data, dict):
            raise ApiError(
                f"Invalid JSON response from: {method.upper()} {path}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return data

    def create_session(
        self,
        *,
        title: str | None = None,
        session_settings: dict[str, Any] | None = None,
        webhook_overrides: dict[str, Any] | None = None,
        workflow_overrides: dict[str, Any] | None = None,
    ) -> str:
        """Create a new session id.

        Calls: POST /api/sessions

        Inputs:
            title: Optional session title.
            session_settings: Optional nested settings map.
                This is intentionally a free-form JSON object on the API side.
            webhook_overrides: Optional session-scoped webhook routing overrides.
                Shape matches BFF `CreateSessionRequest.webhook_overrides`.
            workflow_overrides: Optional session-scoped workflow overrides.
                Shape matches BFF `CreateSessionRequest.workflow_overrides`.

        Returns:
            session_id (UUID string)

        Notes:
            We always send a JSON body (at least `{}`) so this stays compatible
            with server-side request coercion.
        """

        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if session_settings is not None:
            payload["session_settings"] = session_settings
        if webhook_overrides is not None:
            payload["webhook_overrides"] = webhook_overrides
        if workflow_overrides is not None:
            payload["workflow_overrides"] = workflow_overrides

        url = self._rest_url("/api/sessions")
        with httpx.Client(timeout=self._timeout_s) as client:
            resp = client.post(url, headers=self._authz_headers(), json=payload)
        if resp.status_code // 100 != 2:
            raise ApiError(
                "Failed to create session",
                status_code=resp.status_code,
                body=resp.text,
            )
        data = resp.json()
        sid = data.get("session_id")
        if not isinstance(sid, str) or not sid:
            raise ApiError("Invalid response from /api/sessions", status_code=resp.status_code, body=resp.text)
        return sid

    def rename_session(self, session_id: str, *, title: str | None) -> dict[str, Any]:
        """Rename a session.

        Calls: PATCH /api/sessions/:session_id

        Inputs:
            session_id: Session UUID.
            title: New title (may be None/blank; server normalizes blanks).

        Returns:
            Parsed JSON response body.
        """

        url = self._rest_url(f"/api/sessions/{session_id}")
        with httpx.Client(timeout=self._timeout_s) as client:
            resp = client.patch(url, headers=self._authz_headers(), json={"title": title})
        if resp.status_code // 100 != 2:
            raise ApiError("Failed to rename session", status_code=resp.status_code, body=resp.text)
        data = resp.json()
        if not isinstance(data, dict):
            raise ApiError("Invalid response from /api/sessions/:id", status_code=resp.status_code, body=resp.text)
        return data

    def finish_session(self, session_id: str) -> dict[str, Any]:
        """Explicitly mark a session as finished.

        Calls: POST /api/sessions/:session_id/finish

        This is the authoritative BFF state-machine transition to use when a
        client has stopped sending audio. The endpoint is safe to call after
        closing the session WebSockets.
        """

        return self._rest_json("POST", f"/api/sessions/{session_id}/finish")

    def list_recordings(self, *, limit: int = 200, offset: int = 0) -> list[RecordingItem]:
        """List recordings/sessions for the authenticated tenant.

        Calls: GET /api/recordings
        """

        url = self._rest_url(f"/api/recordings?{urlencode({'limit': limit, 'offset': offset})}")
        with httpx.Client(timeout=self._timeout_s) as client:
            resp = client.get(url, headers=self._authz_headers())
        if resp.status_code // 100 != 2:
            raise ApiError("Failed to list recordings", status_code=resp.status_code, body=resp.text)

        payload = resp.json()
        items = payload.get("items")
        if not isinstance(items, list):
            raise ApiError("Invalid response from /api/recordings", status_code=resp.status_code, body=resp.text)

        out: list[RecordingItem] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            sid = it.get("session_id")
            if not isinstance(sid, str):
                continue
            rec_info: RecordingInfo | None = None
            rec = it.get("recording")
            if isinstance(rec, dict):
                rec_info = RecordingInfo(
                    created_at=rec.get("created_at"),
                    duration_s=rec.get("duration_s"),
                    sample_rate=rec.get("sample_rate"),
                    lang=rec.get("lang"),
                )

            out.append(
                RecordingItem(
                    session_id=sid,
                    session_key=it.get("session_key"),
                    title=it.get("title"),
                    status=it.get("status"),
                    started_at=it.get("started_at"),
                    ended_at=it.get("ended_at"),
                    created_at=it.get("created_at"),
                    has_recording=it.get("has_recording"),
                    has_final_transcript=it.get("has_final_transcript"),
                    recording=rec_info,
                )
            )
        return out

    # -----------------
    # Misc / discovery
    # -----------------

    def me(self) -> dict[str, Any]:
        """Return information about the current authenticated principal.

        Calls: GET /api/me

        Returns:
            Parsed JSON response body.
        """

        return self._rest_json("GET", "/api/me")

    # -----------------
    # Speakers (tenant-scoped)
    # -----------------

    def list_speakers(self) -> dict[str, Any]:
        """List enrolled speakers.

        Calls: GET /api/speakers
        """

        return self._rest_json("GET", "/api/speakers")

    def delete_speaker(self, speaker_id: str) -> dict[str, Any]:
        """Delete an enrolled speaker.

        Calls: DELETE /api/speakers/:speaker_id
        """

        return self._rest_json("DELETE", f"/api/speakers/{speaker_id}")

    def create_speaker(self, *, label: str, sample_path: str) -> dict[str, Any]:
        """Enroll a speaker from a WAV sample.

        Calls: POST /api/speakers

        The BFF expects multipart form fields named ``label`` and ``sample``.
        The sample is streamed from disk by httpx and is never loaded into a
        JSON payload.
        """

        url = self._rest_url("/api/speakers")
        sample = Path(sample_path)
        with sample.open("rb") as sample_file:
            files = {"sample": (sample.name, sample_file, "audio/wav")}
            with httpx.Client(timeout=self._timeout_s) as client:
                resp = client.post(
                    url,
                    headers=self._authz_headers(),
                    data={"label": label},
                    files=files,
                )
        if resp.status_code // 100 != 2:
            raise ApiError(
                "Failed to create speaker",
                status_code=resp.status_code,
                body=resp.text,
            )
        data = resp.json()
        if not isinstance(data, dict):
            raise ApiError(
                "Invalid response from /api/speakers",
                status_code=resp.status_code,
                body=resp.text,
            )
        return data

    def create_speaker_from_recording(
        self,
        *,
        session_id: str,
        start_s: float,
        end_s: float,
        label: str,
    ) -> dict[str, Any]:
        """Enroll a new speaker by clipping a sample from a stored recording.

        Calls: POST /api/speaker-enrollment/from-recording

        Inputs:
            session_id: Session UUID.
            start_s/end_s: Clip window in seconds.
            label: Speaker label.
        """

        payload = {"session_id": session_id, "start_s": float(start_s), "end_s": float(end_s), "label": label}
        return self._rest_json("POST", "/api/speaker-enrollment/from-recording", json_body=payload)

    # -----------------
    # API credentials (tenant-scoped)
    # -----------------

    def list_api_credentials(self) -> dict[str, Any]:
        """List tenant API credentials.

        Calls: GET /api/api-credentials
        """

        return self._rest_json("GET", "/api/api-credentials")

    def create_api_credential(self, *, name: str) -> dict[str, Any]:
        """Create a new API credential.

        Calls: POST /api/api-credentials

        Returns:
            Parsed JSON including `client_secret` (returned only once).
        """

        return self._rest_json("POST", "/api/api-credentials", json_body={"name": name})

    def rotate_api_credential(self, credential_id: str) -> dict[str, Any]:
        """Rotate an API credential secret.

        Calls: POST /api/api-credentials/:id/rotate

        Returns:
            Parsed JSON including new `client_secret` (returned only once).
        """

        return self._rest_json("POST", f"/api/api-credentials/{credential_id}/rotate")

    def revoke_api_credential(self, credential_id: str) -> dict[str, Any]:
        """Revoke an API credential.

        Calls: DELETE /api/api-credentials/:id
        """

        return self._rest_json("DELETE", f"/api/api-credentials/{credential_id}")

    # -----------------
    # Webhooks (tenant-scoped)
    # -----------------

    def list_webhooks(self) -> dict[str, Any]:
        """List tenant webhooks.

        Calls: GET /api/webhooks
        """

        return self._rest_json("GET", "/api/webhooks")

    def create_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a webhook.

        Calls: POST /api/webhooks

        Inputs:
            payload: JSON payload per BFF CreateWebhookRequest.
        """

        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        return self._rest_json("POST", "/api/webhooks", json_body=payload)

    def update_webhook(self, webhook_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Update a webhook.

        Calls: PUT /api/webhooks/:id

        Inputs:
            webhook_id: Webhook UUID string.
            patch: JSON patch per BFF UpdateWebhookRequest.
        """

        if not isinstance(patch, dict):
            raise TypeError("patch must be a dict")
        return self._rest_json("PUT", f"/api/webhooks/{webhook_id}", json_body=patch)

    def delete_webhook(self, webhook_id: str) -> dict[str, Any]:
        """Delete a webhook.

        Calls: DELETE /api/webhooks/:id
        """

        return self._rest_json("DELETE", f"/api/webhooks/{webhook_id}")

    def get_webhook_defaults(self) -> dict[str, Any]:
        """Get tenant webhook defaults.

        Calls: GET /api/webhooks/defaults
        """

        return self._rest_json("GET", "/api/webhooks/defaults")

    def set_webhook_defaults(self, webhook_ids: list[str]) -> dict[str, Any]:
        """Set tenant webhook defaults.

        Calls: PUT /api/webhooks/defaults

        Inputs:
            webhook_ids: List of webhook UUID strings.
        """

        return self._rest_json("PUT", "/api/webhooks/defaults", json_body={"webhook_ids": webhook_ids})

    # -----------------
    # Workflows (tenant-scoped)
    # -----------------

    def list_workflows(self) -> dict[str, Any]:
        """List tenant workflows.

        Calls: GET /api/workflows
        """

        return self._rest_json("GET", "/api/workflows")

    def create_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a workflow.

        Calls: POST /api/workflows

        Inputs:
            payload: JSON payload per BFF CreateWorkflowRequest.
        """

        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        return self._rest_json("POST", "/api/workflows", json_body=payload)

    def update_workflow(self, workflow_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Update a workflow.

        Calls: PUT /api/workflows/:id

        Inputs:
            workflow_id: Workflow UUID string.
            patch: JSON patch per BFF UpdateWorkflowRequest.
        """

        if not isinstance(patch, dict):
            raise TypeError("patch must be a dict")
        return self._rest_json("PUT", f"/api/workflows/{workflow_id}", json_body=patch)

    def delete_workflow(self, workflow_id: str) -> dict[str, Any]:
        """Delete a workflow.

        Calls: DELETE /api/workflows/:id
        """

        return self._rest_json("DELETE", f"/api/workflows/{workflow_id}")

    def get_workflow_defaults(self) -> dict[str, Any]:
        """Get tenant workflow defaults.

        Calls: GET /api/workflows/defaults
        """

        return self._rest_json("GET", "/api/workflows/defaults")

    def set_workflow_defaults(self, workflow_ids: list[str]) -> dict[str, Any]:
        """Set tenant workflow defaults.

        Calls: PUT /api/workflows/defaults

        Inputs:
            workflow_ids: List of workflow UUID strings.
        """

        return self._rest_json("PUT", "/api/workflows/defaults", json_body={"workflow_ids": workflow_ids})

    def get_recording(self, session_id: str) -> dict[str, Any]:
        """Fetch recording detail, including transcripts.

        Calls: GET /api/recordings/:session_id

        Returns:
            Parsed JSON as a dict.
        """

        url = self._rest_url(f"/api/recordings/{session_id}")
        with httpx.Client(timeout=self._timeout_s) as client:
            resp = client.get(url, headers=self._authz_headers())
        if resp.status_code // 100 != 2:
            raise ApiError("Failed to fetch recording", status_code=resp.status_code, body=resp.text)
        return resp.json()

    def delete_recording(self, session_id: str) -> dict[str, Any]:
        """Delete a recording (session) for the current tenant.

        Calls: DELETE /api/recordings/:session_id

        Returns:
            Parsed JSON response body.
        """

        url = self._rest_url(f"/api/recordings/{session_id}")
        with httpx.Client(timeout=self._timeout_s) as client:
            resp = client.delete(url, headers=self._authz_headers())
        if resp.status_code // 100 != 2:
            raise ApiError("Failed to delete recording", status_code=resp.status_code, body=resp.text)
        data = resp.json()
        if not isinstance(data, dict):
            raise ApiError(
                "Invalid response from /api/recordings/:session_id (DELETE)",
                status_code=resp.status_code,
                body=resp.text,
            )
        return data

    def list_webhook_delivery_outcomes(self, session_id: str) -> dict[str, Any]:
        """List latest webhook delivery outcomes for a session.

        Calls: GET /api/sessions/:session_id/webhook-delivery-outcomes

        Returns:
            Parsed JSON response body.
        """

        url = self._rest_url(f"/api/sessions/{session_id}/webhook-delivery-outcomes")
        with httpx.Client(timeout=self._timeout_s) as client:
            resp = client.get(url, headers=self._authz_headers())
        if resp.status_code // 100 != 2:
            raise ApiError(
                "Failed to list webhook delivery outcomes",
                status_code=resp.status_code,
                body=resp.text,
            )
        data = resp.json()
        if not isinstance(data, dict):
            raise ApiError(
                "Invalid response from /api/sessions/:id/webhook-delivery-outcomes",
                status_code=resp.status_code,
                body=resp.text,
            )
        return data

    def get_recording_audio_bytes(
        self,
        session_id: str,
        *,
        range_start: int | None = None,
        range_end: int | None = None,
    ) -> bytes:
        """Fetch recording audio (WAV) as bytes.

        Calls: GET /api/recordings/:session_id/audio

        Inputs:
            session_id: Session UUID.
            range_start: Optional Range start byte (inclusive).
            range_end: Optional Range end byte (inclusive).

        Returns:
            Response body bytes.

        Notes:
            - If `range_start`/`range_end` are provided, the SDK sends a
              `Range: bytes=start-end` header.
            - For large recordings, prefer `download_recording_audio()`.
        """

        if range_start is None and range_end is not None:
            # BFF currently does not implement suffix ranges (bytes=-N).
            raise ValueError("range_end without range_start is not supported")

        url = self._rest_url(f"/api/recordings/{session_id}/audio")
        headers = dict(self._authz_headers())
        if range_start is not None or range_end is not None:
            a = "" if range_start is None else str(int(range_start))
            b = "" if range_end is None else str(int(range_end))
            headers["Range"] = f"bytes={a}-{b}"

        with httpx.Client(timeout=self._timeout_s) as client:
            resp = client.get(url, headers=headers)

        if resp.status_code // 100 != 2:
            raise ApiError(
                "Failed to fetch recording audio",
                status_code=resp.status_code,
                body=resp.text,
            )
        return resp.content

    def download_recording_audio(
        self,
        session_id: str,
        out_path: str,
        *,
        chunk_size: int = 1024 * 1024,
        range_start: int | None = None,
        range_end: int | None = None,
    ) -> None:
        """Download recording audio (WAV) to a local file.

        Calls: GET /api/recordings/:session_id/audio

        Inputs:
            session_id: Session UUID.
            out_path: Output filesystem path.
            chunk_size: Streaming chunk size in bytes.
            range_start/range_end: Optional Range start/end bytes.

        Raises:
            ApiError on non-2xx.
        """

        if range_start is None and range_end is not None:
            # BFF currently does not implement suffix ranges (bytes=-N).
            raise ValueError("range_end without range_start is not supported")

        url = self._rest_url(f"/api/recordings/{session_id}/audio")
        headers = dict(self._authz_headers())
        if range_start is not None or range_end is not None:
            a = "" if range_start is None else str(int(range_start))
            b = "" if range_end is None else str(int(range_end))
            headers["Range"] = f"bytes={a}-{b}"

        with httpx.Client(timeout=self._timeout_s) as client:
            with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code // 100 != 2:
                    body = resp.read().decode("utf-8", errors="replace")
                    raise ApiError(
                        "Failed to download recording audio",
                        status_code=resp.status_code,
                        body=body,
                    )
                with open(out_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)

    # -----------------
    # WS helpers
    # -----------------

    def _ws_url(self, path: str, query: dict[str, Any] | None = None) -> str:
        """Convert api_url (http/https) into ws/wss and join path."""

        parsed = urlparse(self._api_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        base = parsed._replace(scheme=scheme)
        base_str = urlunparse(base)
        url = urljoin(base_str, path.lstrip("/"))
        if query:
            url = url + ("?" + urlencode(query))
        return url

    async def _ws_connect(self, url: str):
        try:
            # websockets renamed `extra_headers` -> `additional_headers` in newer
            # versions (e.g. websockets 16). To keep the SDK flexible across
            # environments, detect the supported kwarg at runtime.
            headers = self._authz_headers()
            connect_sig = inspect.signature(websockets.connect)
            if "additional_headers" in connect_sig.parameters:
                return await websockets.connect(
                    url,
                    additional_headers=headers,
                    max_size=8 * 1024 * 1024,
                )
            return await websockets.connect(
                url,
                extra_headers=headers,
                max_size=8 * 1024 * 1024,
            )
        except Exception as e:  # noqa: BLE001
            raise WsError(f"Failed to connect websocket: {url}") from e

    async def iter_events(self, *, session_id: str) -> AsyncIterator[dict[str, Any]]:
        """Connect to `/ws/events` and yield parsed JSON events.

        Yields:
            Event dicts with at least keys like `type`, `session_id`, `seq`, `ts_ms`.
        """

        url = self._ws_url("/ws/events", {"session_id": session_id})
        ws = await self._ws_connect(url)
        try:
            async for msg in ws:
                if isinstance(msg, bytes):
                    # server should send text; ignore binary
                    continue
                try:
                    data = json.loads(msg)
                except Exception as e:  # noqa: BLE001
                    raise WsError("Received non-JSON message on /ws/events") from e
                if isinstance(data, dict):
                    yield data
        finally:
            await ws.close()

    async def iter_workflow_results(
        self,
        *,
        session_id: str,
        workflow_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield only workflow result events from `/ws/events`.

        Inputs:
            session_id: Session UUID.
            workflow_id: Optional workflow UUID to filter by.

        Yields:
            Event dicts with `type == "workflow_result"`.
        """

        async for evt in self.iter_events(session_id=session_id):
            if evt.get("type") != "workflow_result":
                continue
            if workflow_id is not None and str(evt.get("workflow_id")) != str(workflow_id):
                continue
            yield evt

    async def transcribe_pcm(
        self,
        *,
        session_id: str,
        pcm_frames: Iterable[bytes],
        lang: str = "",
        sample_rate: int = 16000,
        # Stream controls (/ws/audio query params)
        realtime: bool | None = None,
        refined: bool | None = None,
        final: bool | None = None,
        store_recording: bool | None = None,
        refinement_window_sec: float | None = None,
        # Realtime tuning (/ws/audio query params)
        rt_partial_enable: bool | None = None,
        window_size: float | None = None,
        overlap: float | None = None,
        emit_every: float | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream PCM16LE frames to `/ws/audio` while yielding `/ws/events`.

        Inputs:
            session_id: Must already exist (create via `create_session`).
            pcm_frames: Iterable of PCM16LE byte chunks.
            lang: Language code ("en", "cs", "")
            sample_rate: Sample rate (default 16000)
            realtime: Whether to run realtime transcription.
                Maps to `/ws/audio` query param `realtime`.
                If omitted, the server default applies.
            refined: Whether to run the refinement pipeline.
                Maps to `/ws/audio` query param `refined`.
            final: Whether to produce final transcript artifacts.
                Maps to `/ws/audio` query param `final`.
            store_recording: Whether to keep the recording for later playback.
                Maps to `/ws/audio` query param `store_recording`.
            refinement_window_sec: Optional refinement window size.
                Maps to `/ws/audio` query param `refinement_window_sec`.
            rt_partial_enable: Whether realtime ASR should emit PARTIAL hypotheses.
                Maps to `/ws/audio` query param `rt_partial_enable`.
            window_size: Optional realtime ASR window size in seconds.
                Mapped to the BFF's `/ws/audio` query param `rt_window_sec`.
            overlap: Optional realtime ASR overlap in seconds.
                Mapped to the BFF's `/ws/audio` query param `rt_overlap_sec`.
            emit_every: Optional realtime ASR emit frequency in seconds.
                Mapped to the BFF's `/ws/audio` query param `rt_emit_every_sec`.

        Returns:
            Async iterator of event dicts.

        Notes:
            This opens two websocket connections:
            - events: receives events
            - audio: sends frames
        """

        events_url = self._ws_url("/ws/events", {"session_id": session_id})
        audio_q: dict[str, Any] = {
            "session_id": session_id,
            "lang": lang,
            "sample_rate": sample_rate,
        }

        def _bool_q(v: bool) -> str:
            # Be explicit: urlencode() would otherwise produce Python's `True`/`False`.
            return "true" if v else "false"

        # Stream controls
        if realtime is not None:
            audio_q["realtime"] = _bool_q(bool(realtime))
        if refined is not None:
            audio_q["refined"] = _bool_q(bool(refined))
        if final is not None:
            audio_q["final"] = _bool_q(bool(final))
        if store_recording is not None:
            audio_q["store_recording"] = _bool_q(bool(store_recording))
        if refinement_window_sec is not None:
            audio_q["refinement_window_sec"] = float(refinement_window_sec)

        # Realtime tuning
        if rt_partial_enable is not None:
            audio_q["rt_partial_enable"] = _bool_q(bool(rt_partial_enable))
        if window_size is not None:
            audio_q["rt_window_sec"] = float(window_size)
        if overlap is not None:
            audio_q["rt_overlap_sec"] = float(overlap)
        if emit_every is not None:
            audio_q["rt_emit_every_sec"] = float(emit_every)

        audio_url = self._ws_url("/ws/audio", audio_q)

        events_ws = await self._ws_connect(events_url)
        audio_ws = await self._ws_connect(audio_url)

        async def _send_audio() -> None:
            try:
                for frame in pcm_frames:
                    if not isinstance(frame, (bytes, bytearray, memoryview)):
                        raise WsError("pcm_frames must yield bytes-like objects")
                    await audio_ws.send(bytes(frame))
            finally:
                # half-close isn't supported; just close.
                await audio_ws.close()

        send_task = None
        try:
            import asyncio

            send_task = asyncio.create_task(_send_audio())
            async for msg in events_ws:
                if isinstance(msg, bytes):
                    continue
                evt = json.loads(msg)
                if isinstance(evt, dict):
                    yield evt
        except json.JSONDecodeError as e:
            raise WsError("Received invalid JSON on /ws/events") from e
        except Exception as e:  # noqa: BLE001
            raise WsError("Websocket transcription failed") from e
        finally:
            try:
                await events_ws.close()
            finally:
                if send_task is not None:
                    try:
                        await send_task
                    except Exception:
                        # audio send failures shouldn't mask event close
                        pass
