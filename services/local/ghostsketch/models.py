"""Validated snapshots shared by persistence and the local HTTP API."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,80}$")]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
def valid_timestamp(value: str) -> str:
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value):
            raise ValueError
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
    except (ValueError, OverflowError):
        raise ValueError("Gebruik een geldige ISO-datum met tijdzone.")
    return value


Timestamp = Annotated[str, StringConstraints(min_length=20, max_length=40), AfterValidator(valid_timestamp)]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Position(Model):
    x: float = Field(ge=-100000, le=100000, allow_inf_nan=False)
    y: float = Field(ge=-100000, le=100000, allow_inf_nan=False)


class GovernReference(Model):
    connection: str = Field(min_length=1, max_length=512)
    recording_id: Identifier
    segment_id: Identifier
    audio_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Stroke(Model):
    id: Identifier
    points: list[Position] = Field(min_length=2, max_length=2000)


class Segment(Model):
    id: Identifier
    text: str = Field(min_length=1, max_length=100000)
    start_ms: int = Field(ge=0, le=86400000)
    end_ms: int = Field(ge=0, le=86400000)
    created_at: Timestamp
    request_id: Identifier
    origin: Literal["text", "microphone", "audio", "govern"]
    govern_source: GovernReference | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_ms < self.start_ms:
            raise ValueError("Het einde van een fragment ligt voor het begin.")
        if not self.text.strip():
            raise ValueError("Een transcriptfragment mag niet leeg zijn.")
        return self


class Card(Model):
    id: Identifier
    type: Literal["idea", "question", "action", "decision"]
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(max_length=2000)
    status: Literal["proposal", "accepted", "rejected"]
    source_segment_ids: list[Identifier] = Field(max_length=40)
    manual: bool
    user_edited: bool
    proposal_key: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")] | None = None
    position: Position

    @model_validator(mode="after")
    def valid_evidence(self):
        if not self.title.strip():
            raise ValueError("Een kaart heeft een titel nodig.")
        if not self.manual and not self.source_segment_ids:
            raise ValueError("Automatische kaarten moeten een gespreksbron hebben.")
        if len(set(self.source_segment_ids)) != len(self.source_segment_ids):
            raise ValueError("Dubbele bronverwijzingen zijn niet toegestaan.")
        return self


class Edge(Model):
    id: Identifier
    source: Identifier
    target: Identifier
    label: str = Field(max_length=160)
    origin: Literal["manual", "suggestion"]

    @model_validator(mode="after")
    def distinct_ends(self):
        if self.source == self.target:
            raise ValueError("Een verbinding moet twee verschillende kaarten hebben.")
        return self


class Source(Model):
    id: Identifier
    title: Title
    url: str = Field(min_length=1, max_length=2048)
    excerpt: str = Field(max_length=10000)
    retrieved_at: Timestamp

    @field_validator("url")
    @classmethod
    def web_url(cls, value):
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError
            _ = parsed.port
        except ValueError:
            raise ValueError("Gebruik een volledige http- of https-bronlink zonder inloggegevens.")
        return value


class ResearchJob(Model):
    id: Identifier
    question_card_id: Identifier
    query: str = Field(min_length=1, max_length=1000)
    status: Literal["prepared", "approved", "documented"]
    sources: list[Source] = Field(default_factory=list, max_length=50)
    approved_at: Timestamp | None = None

    @model_validator(mode="after")
    def valid_state(self):
        if not self.query.strip():
            raise ValueError("Vul een zoektekst in.")
        if self.status != "prepared" and not self.approved_at:
            raise ValueError("Toestemming voor deze zoektekst ontbreekt.")
        if self.status == "documented" and not self.sources:
            raise ValueError("Een gedocumenteerde vraag heeft een bron nodig.")
        return self


class Session(Model):
    id: Identifier
    title: Title
    source: Literal["text", "microphone", "audio", "govern"]
    section: Title = "Algemeen"
    page_text: str = Field(default="", max_length=100000)
    strokes: list[Stroke] = Field(default_factory=list, max_length=500)
    govern_recording: str | None = Field(default=None, max_length=1024)
    created_at: Timestamp
    ended_at: Timestamp | None = None
    segments: list[Segment] = Field(default_factory=list, max_length=2000)
    cards: list[Card] = Field(default_factory=list, max_length=2000)
    edges: list[Edge] = Field(default_factory=list, max_length=4000)
    research_jobs: list[ResearchJob] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def valid_references(self):
        segment_ids = {segment.id for segment in self.segments}
        cards = {card.id: card for card in self.cards}
        requests = [segment.request_id for segment in self.segments]
        if len(set(requests)) != len(requests):
            raise ValueError("Een invoeropdracht mag maar één transcriptfragment opleveren.")
        for card in self.cards:
            if not set(card.source_segment_ids).issubset(segment_ids):
                raise ValueError("Een kaart verwijst naar een ontbrekend transcriptfragment.")
        for edge in self.edges:
            if edge.source not in cards or edge.target not in cards:
                raise ValueError("Een verbinding verwijst naar een ontbrekende kaart.")
        for job in self.research_jobs:
            if job.question_card_id not in cards or cards[job.question_card_id].type != "question":
                raise ValueError("Onderzoek moet bij een bestaande vraagkaart horen.")
        return self


class Project(Model):
    id: Identifier
    title: Title
    description: str = Field(default="", max_length=2000)
    revision: int = Field(ge=0)
    created_at: Timestamp
    updated_at: Timestamp
    sessions: list[Session] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [self.id]
        for session in self.sessions:
            ids.append(session.id)
            for collection in (session.segments, session.cards, session.edges, session.research_jobs, session.strokes):
                ids.extend(item.id for item in collection)
            for job in session.research_jobs:
                ids.extend(source.id for source in job.sources)
        if len(set(ids)) != len(ids):
            raise ValueError("Gebruik voor ieder onderdeel een unieke ID.")
        return self


class Settings(Model):
    organizer: Literal["rules", "ollama"] = "rules"
    ollama_model: str = Field(default="", max_length=150)
    language: Literal["nl"] = "nl"
    # Legacy setting: GhostSketch itself keeps no raw audio; Govern archives it.
    recordings_retained: Literal[False] = False

    @model_validator(mode="after")
    def model_selected(self):
        if self.organizer == "ollama" and not self.ollama_model.strip():
            raise ValueError("Kies een lokaal Ollama-model.")
        return self


class NewProject(Model):
    title: Title
    description: str = Field(default="", max_length=2000)


class SaveProject(Model):
    expected_revision: int = Field(ge=0)
    project: Project


class TextInput(Model):
    text: str = Field(min_length=1, max_length=50000)
    request_id: Identifier
    start_ms: int = Field(default=0, ge=0, le=86400000)
    end_ms: int = Field(default=0, ge=0, le=86400000)

    @model_validator(mode="after")
    def content_and_range(self):
        if not self.text.strip():
            raise ValueError("Plak eerst de tekst die je wilt verwerken.")
        if self.end_ms < self.start_ms:
            raise ValueError("Het einde van een fragment ligt voor het begin.")
        return self


class AudioInput(TextInput):
    # Preserve the complete bounded whisper response; pasted text has a smaller UI limit.
    text: str = Field(min_length=1, max_length=100000)
