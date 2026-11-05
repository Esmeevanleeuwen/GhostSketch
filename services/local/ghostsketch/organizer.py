"""Small, deterministic Dutch note rules; this module does not call an AI model.

Candidates preserve source words. They are suggestions, never approved decisions.
Unrecognised chatter produces no card rather than an invented interpretation.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal, TypedDict

CardKind = Literal["idea", "question", "action", "decision"]


class Candidate(TypedDict):
    type: CardKind
    title: str
    text: str
    source_segment_ids: list[str]


_SENTENCES = re.compile(r"(?<=[.!?])\s+|[\r\n]+")
_BULLET = re.compile(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)")
_NOISE = re.compile(
    r"^[\s\W]*(?:stilte|silence|muziek|music|ruis|noise|onverstaanbaar|"
    r"inaudible|uh|uhm|eh|ehm|hm|hmm|ja|nee|ok[eé]?|inderdaad)[\s\W]*$",
    re.IGNORECASE,
)
_TENTATIVE = re.compile(
    r"^(?:wat\s+als\b|misschien\b|eventueel\b|stel\s+(?:dat|je\s+voor)\b|"
    r"we\s+zouden\b|ik\s+zou\b)", re.IGNORECASE,
)
_QUESTION = re.compile(
    r"^(?:maar\s+)?(?:hoe|waarom|wanneer|waarmee|waarvoor|waar|wie|wat|of|welk(?:e)?|"
    r"kan|kunnen|werkt|werken|ondersteunt|ondersteunen|mag|mogen|moet|moeten|"
    r"is|zijn|heeft|hebben|zou|zouden)\b|"
    r"^(?:ik|we)\s+(?:vraag|vragen)\s+(?:me|ons)\s+af\b|"
    r"^(?:ik|we)\s+(?:weet|weten)\s+niet\s+of\b",
    re.IGNORECASE,
)
_DECISION = re.compile(
    r"^(?:we\s+(?:besluiten|kiezen)\b|"
    r"we\s+hebben\s+(?:besloten|afgesproken|gekozen)\b|"
    r"(?:het\s+)?besluit\s*[:：]|afgesproken\s*[:：]|"
    r"(?:de\s+)?afspraak\s+is\b|we\s+spreken\s+af\b)",
    re.IGNORECASE,
)
_ACTION = re.compile(
    r"^(?:laten\s+we\b|volgende\s+stap\s*[:：]?|actie\s*[:：]|"
    r"we\s+(?:moeten|gaan)\b|ik\s+(?:zal|ga)\b|"
    r"(?:onderzoek|test|controleer|maak|bouw|probeer|vergelijk|zoek|bekijk|"
    r"noteer|implementeer|installeer|meet)\b|"
    r"(?:uitzoeken|onderzoeken|testen|controleren|bouwen|vergelijken)\b)",
    re.IGNORECASE,
)
_IDEA = re.compile(
    r"^(?:(?:een|het)\s+idee\b|idee\s*[:：]|"
    r"(?:ik|we)\s+(?:wil|willen|denk|denken|kan|kunnen)\b|"
    r"het\s+zou\b|voorstel\s*[:：]|"
    r"(?:een|nieuwe?|draagbare?)\s+.{8,})",
    re.IGNORECASE,
)


def _key(text: str) -> str:
    """Ignore case, typographic variants and sentence-end punctuation for dedup."""
    return " ".join(
        re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFKC", text).casefold()).split()
    )


def _bounded(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    # Keep an actual prefix, rather than adding a made-up continuation.
    prefix = text[:limit]
    boundary = prefix.rfind(" ")
    return prefix[:boundary].rstrip() if boundary >= limit // 2 else prefix


def _kind(sentence: str) -> CardKind | None:
    if _TENTATIVE.search(sentence):
        return "idea"
    if _QUESTION.search(sentence) or sentence.rstrip('"\u201d\u2019\'').endswith("?"):
        return "question"
    if _DECISION.search(sentence):
        # A conditional decision is still a possibility, not an agreed decision.
        if re.search(r"\b(?:misschien|eventueel|mogelijk|als)\b", sentence, re.IGNORECASE):
            return "idea"
        return "decision"
    if _ACTION.search(sentence):
        return "action"
    if _IDEA.search(sentence):
        return "idea"
    return None


def extract_rules(text: str, segment_id: str) -> list[Candidate]:
    """Extract up to twelve literal suggestions using clear Dutch cue phrases.

    Types indicate an intent in the source sentence; the caller must keep every
    candidate in proposal status. Source IDs are supplied, never inferred.
    """
    if not isinstance(text, str):
        raise TypeError("text moet een tekenreeks zijn")
    if not isinstance(segment_id, str) or not segment_id.strip():
        raise ValueError("Een bestaande transcript-ID is vereist")
    candidates: list[Candidate] = []
    seen: set[str] = set()
    # The API has its own smaller input limit; this keeps direct calls bounded too.
    for fragment in _SENTENCES.split(text[:100_000]):
        sentence = _BULLET.sub("", fragment).strip()
        if not sentence or _NOISE.fullmatch(sentence):
            continue
        # Recognise intent through quotation marks without changing the source text.
        probe = sentence.lstrip('"\u201c\u2018\' ')
        if not re.search(r"[A-Za-zÀ-ÿ]{2}", probe):
            continue
        kind = _kind(probe)
        key = _key(probe)
        if kind is None or not key or key in seen:
            continue
        seen.add(key)
        literal = _bounded(sentence, 2000)
        candidates.append({
            "type": kind,
            "title": _bounded(literal, 120),
            "text": literal,
            "source_segment_ids": [segment_id],
        })
        if len(candidates) == 12:
            break
    return candidates
