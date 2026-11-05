"""Fixed-scope storage connection. GhostSketch handles audio processing and linking."""
import hashlib
import json
import os
from urllib.parse import urlsplit
from uuid import UUID
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError
from .adapters import AdapterError

MAX_ARCHIVE_BYTES = 16 * 1024 * 1024

class Recording(BaseModel):
    id: UUID
    filename: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    duration_ms: int = Field(ge=1, le=1800000)
    status: Literal['pending', 'ready']

class Fragment(BaseModel):
    id: UUID
    sequence: int = Field(ge=0, le=300)
    start_ms: int = Field(ge=0, le=1800000)
    end_ms: int = Field(ge=1, le=1800000)
    text: str = Field(max_length=100000)

class Transcript(Recording):
    segments: list[Fragment] = Field(max_length=301)

class GovernSource:
    def __init__(self, url=None, token=None, transport=None):
        self.url = url if url is not None else os.environ.get('GHOSTSKETCH_GOVERN_URL', '')
        self.token = token if token is not None else os.environ.get('GHOSTSKETCH_GOVERN_TOKEN', '')
        self.transport = transport
        if self.url:
            p = urlsplit(self.url)
            if (p.scheme != 'http' or p.hostname not in {'localhost','127.0.0.1','::1'}
                or p.path not in {'/dictation-feed.php','/ghostsketch-storage.php'}
                or p.username or p.password or p.query or p.fragment):
                raise ValueError('Gebruik een lokaal Govern-adres met /ghostsketch-storage.php.')
            _ = p.port

    @property
    def configured(self):
        return bool(self.url and len(self.token)>=32)

    @property
    def writable(self):
        return self.configured and urlsplit(self.url).path=='/ghostsketch-storage.php'

    @property
    def identity(self):
        # Stable provenance for notebooks created with the earlier read-only feed.
        p = urlsplit(self.url)
        return p._replace(path='/dictation-feed.php').geturl()

    def require_storage(self):
        if not self.writable:
            raise AdapterError('Koppel GhostSketch aan de Govern-opslag via .env. Opnemen en transcriberen blijven in GhostSketch.')

    def request(self, action, *, recording_id=None, method='GET', files=None, data=None, binary=False):
        if not self.configured:
            raise AdapterError('Stel de opslagkoppeling in via .env en herstart GhostSketch.')
        params = {'action':action} if self.writable else {}
        if recording_id: params['id']=str(recording_id)
        try:
            with httpx.Client(timeout=45,follow_redirects=False,trust_env=False,transport=self.transport) as client:
                with client.stream(method,self.url,params=params,files=files,json=data,
                                   headers={'Authorization':'Bearer '+self.token}) as response:
                    if response.status_code not in {200,201}:
                        raise AdapterError('De Govern-opslag is niet bereikbaar of heeft de aanvraag geweigerd.',409 if response.status_code==409 else 503)
                    content=bytearray()
                    for part in response.iter_bytes():
                        content.extend(part)
                        if len(content)>(MAX_ARCHIVE_BYTES if binary else 4*1024*1024):
                            raise AdapterError('Het opslagantwoord is te groot.')
            if binary: return bytes(content)
            envelope=json.loads(content)
            if not isinstance(envelope,dict) or envelope.get('ok') is not True: raise ValueError
            return envelope['data']
        except AdapterError: raise
        except (httpx.HTTPError,ValueError,KeyError,TypeError) as exc:
            raise AdapterError('De Govern-opslag gaf geen geldig antwoord. Controleer de koppeling.') from exc

    @staticmethod
    def transcript(data, recording_id, ready=True):
        try:
            transcript=Transcript.model_validate(data)
            if str(transcript.id)!=str(recording_id): raise ValueError
            if ready and transcript.status!='ready':
                raise AdapterError('Deze opname moet nog in GhostSketch worden getranscribeerd.',409)
            previous=0; seen=set()
            for index,fragment in enumerate(transcript.segments):
                if (fragment.sequence!=index or fragment.start_ms!=previous or fragment.end_ms<=fragment.start_ms
                    or fragment.end_ms>transcript.duration_ms or fragment.id in seen): raise ValueError
                seen.add(fragment.id); previous=fragment.end_ms
            if transcript.status=='ready' and previous!=transcript.duration_ms: raise ValueError
            return transcript
        except (ValueError,ValidationError) as exc:
            raise AdapterError('Het opgeslagen transcript is ongeldig.') from exc

    def read(self,recording_id=None,ready=True):
        data=self.request('recording' if recording_id else 'list',recording_id=recording_id)
        if recording_id: return self.transcript(data,recording_id,ready)
        try:
            rows=data['recordings']
            if not isinstance(rows,list) or len(rows)>500: raise ValueError
            return [Recording.model_validate(row) for row in rows]
        except (ValueError,KeyError,TypeError,ValidationError) as exc:
            raise AdapterError('De lijst met opnames is ongeldig.') from exc

    def archive(self,content,filename):
        self.require_storage()
        if not content or len(content)>MAX_ARCHIVE_BYTES:
            raise AdapterError('Kies een opname van maximaal 16 MiB.',413)
        data=self.request('upload',method='POST',files={'file':(filename,content,'application/octet-stream')})
        try: recording=Recording.model_validate(data)
        except ValidationError as exc: raise AdapterError('De opslagbevestiging is ongeldig.') from exc
        if recording.sha256!=hashlib.sha256(content).hexdigest():
            raise AdapterError('De opgeslagen opname komt niet overeen met het bestand.')
        return recording

    def audio(self,recording):
        self.require_storage()
        content=self.request('audio',recording_id=recording.id,binary=True)
        if hashlib.sha256(content).hexdigest()!=recording.sha256:
            raise AdapterError('De opname is gewijzigd. Laad de bron opnieuw.')
        return content

    def complete(self,recording,text):
        self.require_storage()
        if len(text)>100000: raise AdapterError('Het transcript is te groot voor één opname.',422)
        data=self.request('complete',method='POST',data={'id':str(recording.id),'sha256':recording.sha256,'text':text})
        result = self.transcript(data,recording.id)
        if (result.sha256 != recording.sha256 or result.duration_ms != recording.duration_ms
            or len(result.segments) != 1 or result.segments[0].text != text):
            raise AdapterError('De opgeslagen transcriptie komt niet overeen met het verwerkte gesprek.')
        return result
