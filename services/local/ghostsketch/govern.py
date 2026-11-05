"""Read-only, server-configured Govern transcript connection. Never fetch audio."""
import os
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, ValidationError
from .adapters import AdapterError


class Recording(BaseModel):
    id: UUID
    filename: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    duration_ms: int = Field(ge=1, le=1800000)
    status: str


class Fragment(BaseModel):
    id: UUID
    sequence: int = Field(ge=0, le=300)
    start_ms: int = Field(ge=0, le=1800000)
    end_ms: int = Field(ge=1, le=1800000)
    text: str = Field(max_length=8000)


class Transcript(Recording):
    segments: list[Fragment] = Field(max_length=301)


class GovernSource:
    def __init__(self, url=None, token=None, transport=None):
        self.url = url if url is not None else os.environ.get('GHOSTSKETCH_GOVERN_URL', '')
        self.token = token if token is not None else os.environ.get('GHOSTSKETCH_GOVERN_TOKEN', '')
        self.transport = transport
        if self.url:
            p = urlsplit(self.url)
            if (p.scheme != 'http' or p.hostname not in {'localhost', '127.0.0.1', '::1'}
                or p.path != '/dictation-feed.php' or p.username or p.password or p.query or p.fragment):
                raise ValueError('Gebruik een lokaal Govern-adres met /dictation-feed.php.')
            _ = p.port

    @property
    def configured(self):
        return bool(self.url and len(self.token) >= 32)

    @property
    def identity(self):
        return self.url

    def read(self, recording_id=None):
        if not self.configured:
            raise AdapterError('Stel de Govern-koppeling in via .env en herstart GhostSketch.')
        try:
            with httpx.Client(timeout=15, follow_redirects=False, trust_env=False, transport=self.transport) as client:
                with client.stream('GET', self.url, params={'id': str(recording_id)} if recording_id else {},
                                   headers={'Authorization': 'Bearer ' + self.token}) as response:
                    if response.status_code != 200:
                        raise AdapterError('Govern is niet bereikbaar of de toegangssleutel klopt niet.')
                    content = bytearray()
                    for part in response.iter_bytes():
                        content.extend(part)
                        if len(content) > 4 * 1024 * 1024:
                            raise AdapterError('Het Govern-antwoord is te groot.')
            import json
            envelope = json.loads(content)
            if envelope.get('ok') is not True:
                raise ValueError
            data = envelope['data']
            if recording_id:
                transcript = Transcript.model_validate(data)
                if str(transcript.id) != str(recording_id) or transcript.status != 'ready':
                    raise AdapterError('Deze opname is nog niet volledig getranscribeerd in Govern.', 409)
                previous = 0
                seen = set()
                for index, fragment in enumerate(transcript.segments):
                    if (fragment.sequence != index or fragment.start_ms != previous
                        or fragment.end_ms <= fragment.start_ms or fragment.end_ms > transcript.duration_ms
                        or fragment.id in seen):
                        raise ValueError
                    seen.add(fragment.id)
                    previous = fragment.end_ms
                if previous != transcript.duration_ms:
                    raise ValueError
                return transcript
            recordings = data['recordings']
            if not isinstance(recordings, list) or len(recordings) > 500:
                raise ValueError
            return [Recording.model_validate(row) for row in recordings]
        except AdapterError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError, ValidationError) as exc:
            raise AdapterError('Govern gaf geen geldig transcriptantwoord. Controleer de koppeling.') from exc
