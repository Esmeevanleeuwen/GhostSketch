"""Local HTTP boundary. GhostSketch processes audio; Govern archives the sources."""
from __future__ import annotations

import os
import hashlib
from uuid import UUID
import logging
import secrets
import threading
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from typing import Annotated

from .govern import GovernSource, MAX_ARCHIVE_BYTES
from . import __version__
from .adapters import AdapterError, LocalAdapters
from .models import AudioInput, Card, Identifier, NewProject, Project, SaveProject, Settings, TextInput
from .organizer import extract_rules
from .store import Store, StoreError, default_data_dir

JSON_LIMIT = 8 * 1024 * 1024
LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def _safe_host(value: str):
    try:
        parsed = urlsplit("http://" + value)
        return parsed.hostname in LOOPBACK and parsed.username is None and parsed.password is None and parsed.path == "" and parsed.query == "" and parsed.fragment == "" and (parsed.port is None or 1 <= parsed.port <= 65535)
    except ValueError:
        return False


def _safe_origin(origin: str, host: str):
    try:
        value = urlsplit(origin)
        target = urlsplit("http://" + host)
        return value.scheme == "http" and value.hostname in LOOPBACK and value.username is None and value.password is None and not value.path and not value.query and not value.fragment and (value.port or 80) in {8000, 5173, target.port or 80}
    except ValueError:
        return False


def create_app(data_dir=None, adapters=None, frontend_dir=None, govern=None) -> FastAPI:
    store = Store(data_dir or default_data_dir())
    local = adapters if adapters is not None else LocalAdapters(
        os.environ.get("GHOSTSKETCH_OLLAMA_URL", "http://127.0.0.1:11434"),
        os.environ.get("GHOSTSKETCH_WHISPER_URL", "http://127.0.0.1:8081") or None,
    )
    source = govern if govern is not None else GovernSource()
    app = FastAPI(title="GhostSketch lokaal", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.adapters = store, local
    app.state.token = secrets.token_urlsafe(32)
    locks = [threading.RLock() for _ in range(32)]
    recording_locks = [threading.RLock() for _ in range(32)]
    frontend = Path(frontend_dir) if frontend_dir else Path(__file__).resolve().parents[3] / "apps/web/dist"
    frontend = frontend.resolve()

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        host = request.headers.get("host", "")
        origin = request.headers.get("origin")
        if not _safe_host(host) or (origin is not None and not _safe_origin(origin, host)):
            return JSONResponse({"detail": "Dit adres heeft geen toegang tot de lokale GhostSketch-app."}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            token = request.headers.get("x-ghostsketch-token", "")
            if not secrets.compare_digest(token, app.state.token):
                return JSONResponse({"detail": "De lokale sessiesleutel ontbreekt of is verlopen. Herlaad de app."}, status_code=403)
            limit = MAX_ARCHIVE_BYTES + 65536 if request.url.path.endswith("/audio") else JSON_LIMIT
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": "Ongeldige verzoeklengte."}, status_code=400)
            if length < 0 or length > limit:
                return JSONResponse({"detail": "Het bestand of verzoek is te groot. Audio mag maximaal 16 MiB zijn."}, status_code=413)
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    return JSONResponse({"detail": "Het bestand of verzoek is te groot."}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.exception_handler(StoreError)
    @app.exception_handler(AdapterError)
    async def known_error(request, exc):
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    @app.exception_handler(ValidationError)
    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()[:20]]
        return JSONResponse({"detail": "Deze gegevens zijn niet geldig. Controleer tekst, datums en verwijzingen.", "errors": errors}, status_code=422)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/bootstrap")
    def bootstrap():
        return {"token": app.state.token, "projects": store.list(), "settings": store.settings(), "capabilities": {**local.capabilities(), "govern_storage": source.writable}}

    @app.get("/api/capabilities")
    def capabilities():
        return {**local.capabilities(), "govern_storage": source.writable}

    @app.get("/api/projects")
    def list_projects():
        return store.list()

    @app.post("/api/projects")
    def create_project(body: NewProject):
        return store.create(body)

    @app.post("/api/projects/import")
    def import_project(body: Project):
        return store.import_project(body)

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: Identifier):
        return store.get(project_id)

    @app.put("/api/projects/{project_id}")
    def save_project(project_id: Identifier, body: SaveProject):
        return store.save(project_id, body.project, body.expected_revision)

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: Identifier):
        store.delete(project_id)
        return {"ok": True}

    @app.put("/api/settings")
    def save_settings(body: Settings):
        return store.save_settings(body)

    def envelope(project, session_id, organizer, warnings):
        return {"project": project, "session_id": session_id, "organizer": organizer, "warnings": warnings}

    def ingest(session_id, body: TextInput, origin, govern_source=None):
        with locks[hash(session_id) % len(locks)]:
            settings = store.settings()
            project, segment, done = store.reserve_segment(session_id, body, origin, settings.organizer, govern_source)
            if done:
                previous = store.outcome(session_id, body.request_id)
                if previous:
                    return envelope(previous[0], session_id, previous[1], previous[2])
                return envelope(project, session_id, settings.organizer, ["Deze tekst was al bewaard; er zijn geen dubbele voorstellen gemaakt."])
            warnings = []
            try:
                if settings.organizer == "rules":
                    candidates = extract_rules(body.text, segment.id)
                else:
                    session = next(s for s in project.sessions if s.id == session_id)
                    context = "\n".join(s.text for s in session.segments if s.id != segment.id)[-3000:]
                    candidates = local.organize(body.text, settings.ollama_model, segment.id, context)
                if not isinstance(candidates, list) or len(candidates) > 20:
                    raise AdapterError("De lokale organizer gaf te veel of ongeldige voorstellen.", 502)
                for candidate in candidates:
                    if not isinstance(candidate, dict) or set(candidate) != {"type", "title", "text", "source_segment_ids"} or candidate["source_segment_ids"] != [segment.id]:
                        raise AdapterError("De lokale organizer gaf ongeldige bronverwijzingen.", 502)
                    Card(id="validation", status="proposal", manual=False, user_edited=False, position={"x": 0, "y": 0}, **candidate)
            except (AdapterError, ValidationError) as exc:
                message = exc.message if isinstance(exc, AdapterError) else "Het antwoord bevatte ongeldige kaartgegevens."
                warnings = ["De tekst is bewaard, maar er zijn geen voorstellen gemaakt. " + message]
                candidates = []
            except Exception as exc:
                logging.getLogger("ghostsketch").error("Onverwachte organizerfout (%s).", type(exc).__name__)
                warnings = ["De tekst is bewaard. De lokale organizer kon dit fragment door een onverwachte fout niet verwerken; er zijn geen voorstellen toegevoegd."]
                candidates = []
            project, warnings = store.complete_segment(session_id, segment.id, body.request_id, candidates, warnings)
            return envelope(project, session_id, settings.organizer, warnings)

    @app.get("/api/govern/recordings")
    def govern_recordings():
        return {"configured": source.configured, "writable": source.writable, "recordings": source.read() if source.configured else []}

    def ensure_transcript(recording_id, content=None):
        with recording_locks[hash(str(recording_id)) % len(recording_locks)]:
            recording = source.read(recording_id, ready=False)
            if recording.status == "ready":
                return recording
            source.require_storage()
            if recording.segments:
                raise AdapterError("Deze oudere opname heeft een gedeeltelijk transcript. De bron blijft bewaard; gebruik een nieuwe opname voor de nieuwe route.", 409)
            try:
                audio = content if content is not None else source.audio(recording)
                text, _ = local.transcribe(audio, recording.filename)
                return source.complete(recording, text)
            except AdapterError as exc:
                raise AdapterError("De opname staat in Govern. Probeer vanuit GhostSketch opnieuw via Opnames. " + exc.message, exc.status_code) from exc

    @app.post("/api/projects/{project_id}/govern/{recording_id}")
    def import_govern(project_id: Identifier, recording_id: UUID):
        store.get(project_id)
        transcript = ensure_transcript(recording_id)
        identity = source.identity + "#" + str(transcript.id) + ":" + transcript.sha256
        page_id = store.govern_page(project_id, identity, transcript.filename)
        warnings = []
        for fragment in transcript.segments:
            if not fragment.text.strip():
                continue
            request_id = hashlib.sha256((identity + ":" + str(fragment.sequence)).encode()).hexdigest()
            result = ingest(page_id, AudioInput(text=fragment.text, request_id=request_id,
                start_ms=fragment.start_ms, end_ms=fragment.end_ms), "govern", {
                    "connection": source.identity, "recording_id": str(transcript.id),
                    "segment_id": str(fragment.id), "audio_sha256": transcript.sha256})
            warnings.extend(result["warnings"])
        return envelope(store.get(project_id), page_id, store.settings().organizer, list(dict.fromkeys(warnings)))

    @app.post("/api/sessions/{session_id}/segments")
    def add_segment(session_id: Identifier, body: TextInput):
        return ingest(session_id, body, "text")

    @app.post("/api/sessions/{session_id}/audio")
    def add_audio(
        session_id: Identifier,
        file: Annotated[UploadFile, File()],
        request_id: Annotated[str, Form(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")],
        start_ms: Annotated[int, Form(ge=0, le=86400000)] = 0,
    ):
        try:
            with locks[hash(session_id) % len(locks)]:
                project = store.session_project(session_id)
                session = next(s for s in project.sessions if s.id == session_id)
                source.require_storage()
                content = file.file.read(MAX_ARCHIVE_BYTES + 1)
                if not content or len(content) > MAX_ARCHIVE_BYTES:
                    raise AdapterError("Kies een opname van maximaal 16 MiB.", 413)
                checksum = hashlib.sha256(content).hexdigest()
                previous = next((s for s in session.segments if s.request_id == request_id), None)
                if previous and (not previous.govern_source or previous.govern_source.audio_sha256 != checksum or previous.start_ms != start_ms):
                    raise AdapterError("Deze aanvraag hoort bij een andere opname.",409)
                # An uncertain HTTP response can be retried without duplicating the note.
                same = previous or next((s for s in session.segments if s.govern_source
                    and s.govern_source.audio_sha256 == checksum and s.start_ms == start_ms), None)
                if same:
                    outcome = store.outcome(session_id, same.request_id)
                    if outcome:
                        return envelope(outcome[0],session_id,outcome[1],outcome[2])
                    request_id = same.request_id
                recording = source.archive(content, file.filename or "opname.wav")
                transcript = ensure_transcript(recording.id, content)
                if len(transcript.segments) != 1:
                    raise AdapterError("Deze oudere opname heeft meerdere transcriptfragmenten. Open deze via Opnames om alle bronverwijzingen te behouden.",409)
                text = transcript.segments[0].text
                if not text.strip():
                    return envelope(store.session_project(session_id), session_id, store.settings().organizer,
                        ["Er is geen spraak herkend. De opname is in Govern bewaard; er zijn geen kaarten toegevoegd."])
                try:
                    body = AudioInput(text=text, request_id=request_id, start_ms=start_ms, end_ms=start_ms + transcript.duration_ms)
                except ValidationError as exc:
                    raise AdapterError("Het transcript is bewaard, maar past niet op deze pagina.",422) from exc
                reference = {"connection":source.identity,"recording_id":str(transcript.id),
                    "segment_id":str(transcript.segments[0].id),"audio_sha256":transcript.sha256}
                return ingest(session_id,body,"microphone" if session.source=="microphone" else "audio",reference)

        finally:
            file.file.close()

    @app.get("/{path:path}")
    def frontend_route(path: str):
        if path == "api" or path.startswith("api/"):
            return JSONResponse({"detail": "Deze API-route bestaat niet."}, status_code=404)
        candidate = (frontend / path).resolve()
        if not candidate.is_relative_to(frontend):
            return JSONResponse({"detail": "Dit bestand is niet beschikbaar."}, status_code=404)
        if path and candidate.is_file():
            return FileResponse(candidate)
        index = frontend / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"detail": "De webapp is nog niet gebouwd. Voer npm run build uit in apps/web."}, status_code=503)

    return app
