"""SQLite-backed snapshots with revision checks and durable ingestion jobs."""
from __future__ import annotations
import hashlib
import json
import os
import re
import sqlite3
import sys
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from .models import Card, NewProject, Project, Segment, Session, Settings, TextInput, now_iso

# Below the HTTP snapshot limit, so every stored project can still be edited/exported.
MAX_PROJECT_BYTES = 7 * 1024 * 1024


class StoreError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message, self.status_code = message, status_code


def normalize(text: str) -> str:
    return re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


def proposal_key(kind: str, text: str) -> str:
    return hashlib.sha256((kind + "\0" + normalize(text)).encode("utf-8")).hexdigest()


def history_key(value: str) -> str:
    # v0.1 development databases initially stored the unhashed signature.
    if re.fullmatch(r"[a-f0-9]{64}", value):
        return value
    kind, text = json.loads(value)
    return proposal_key(kind, text)


def project_size(project: Project, document: str | None = None) -> int:
    """Reserve enough space for UUID rekeying so an exported project stays importable."""
    identifiers = [project.id]
    for session in project.sessions:
        identifiers.append(session.id)
        for collection in (session.segments, session.cards, session.edges, session.research_jobs, session.strokes):
            identifiers.extend(item.id for item in collection)
        identifiers.extend(segment.request_id for segment in session.segments)
        for card in session.cards:
            identifiers.extend(card.source_segment_ids)
        for edge in session.edges:
            identifiers.extend((edge.source, edge.target))
        for job in session.research_jobs:
            identifiers.append(job.question_card_id)
            identifiers.extend(source.id for source in job.sources)
    return len((document or project.model_dump_json()).encode("utf-8")) + sum(max(0,36-len(value)) for value in identifiers) + max(0,24-len(project.created_at)) + max(0,24-len(project.updated_at))


def default_data_dir() -> Path:
    if os.environ.get("GHOSTSKETCH_DATA_DIR"):
        return Path(os.environ["GHOSTSKETCH_DATA_DIR"]).expanduser().resolve()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "GhostSketch"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/GhostSketch"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "ghostsketch"


class Store:
    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path = self.data_dir / "ghostsketch.sqlite3"
        with self.connection() as conn:
            conn.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS session_lookup(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS proposal_history(session_id TEXT NOT NULL REFERENCES session_lookup(id) ON DELETE CASCADE,signature TEXT NOT NULL,PRIMARY KEY(session_id,signature));
                CREATE TABLE IF NOT EXISTS ingestion_jobs(session_id TEXT NOT NULL REFERENCES session_lookup(id) ON DELETE CASCADE,request_id TEXT NOT NULL,fragment_id TEXT NOT NULL,fingerprint TEXT NOT NULL,state TEXT NOT NULL,organizer TEXT NOT NULL,warnings TEXT NOT NULL DEFAULT '[]',PRIMARY KEY(session_id,request_id));
            ''')
            if "warnings" not in {r[1] for r in conn.execute("PRAGMA table_info(ingestion_jobs)")}:
                conn.execute("ALTER TABLE ingestion_jobs ADD COLUMN warnings TEXT NOT NULL DEFAULT '[]'")
            conn.execute("INSERT OR IGNORE INTO settings(id,document) VALUES(1,?)", (Settings().model_dump_json(),))
        try:
            self.db_path.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def connection(self, write=False):
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _read(self, conn, project_id):
        row = conn.execute("SELECT document FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise StoreError("Dit schetsboek bestaat niet meer.", 404)
        return Project.model_validate_json(row["document"])

    def get(self, project_id):
        with self.connection() as conn:
            return self._read(conn, project_id)

    def _session_project(self, conn, session_id):
        row = conn.execute("SELECT project_id FROM session_lookup WHERE id=?", (session_id,)).fetchone()
        if not row:
            raise StoreError("Deze sessie bestaat niet meer.", 404)
        return self._read(conn, row["project_id"])

    def session_project(self, session_id):
        with self.connection() as conn:
            return self._session_project(conn, session_id)

    def _write(self, conn, project):
        for session in project.sessions:
            for card in session.cards:
                if not card.manual and card.proposal_key is None:
                    card.proposal_key = proposal_key(card.type, card.text or card.title)
        project = Project.model_validate(project.model_dump())
        document = project.model_dump_json()
        if project_size(project, document) > MAX_PROJECT_BYTES:
            raise StoreError("Dit schetsboek is vol (maximaal 7 MiB tekst en kaarten). Exporteer het en maak een nieuw schetsboek; je bestaande gegevens zijn ongewijzigd.", 413)
        conn.execute("UPDATE projects SET revision=?,document=? WHERE id=?", (project.revision, document, project.id))
        active = {s.id for s in project.sessions}
        current = {r["id"] for r in conn.execute("SELECT id FROM session_lookup WHERE project_id=?", (project.id,))}
        for stale in current - active:
            conn.execute("DELETE FROM session_lookup WHERE id=?", (stale,))
        for session in project.sessions:
            existing = conn.execute("SELECT project_id FROM session_lookup WHERE id=?", (session.id,)).fetchone()
            if existing and existing["project_id"] != project.id:
                raise StoreError("Een sessie-ID wordt al door een ander schetsboek gebruikt.", 422)
            conn.execute("INSERT OR IGNORE INTO session_lookup(id,project_id) VALUES(?,?)", (session.id, project.id))
            for card in session.cards:
                if not card.manual:
                    signature = card.proposal_key or proposal_key(card.type, card.text or card.title)
                    conn.execute("INSERT OR IGNORE INTO proposal_history(session_id,signature) VALUES(?,?)", (session.id, signature))
            segment_ids = {s.id for s in session.segments}
            for job in conn.execute("SELECT request_id,fragment_id FROM ingestion_jobs WHERE session_id=?", (session.id,)).fetchall():
                if job["fragment_id"] not in segment_ids:
                    conn.execute("DELETE FROM ingestion_jobs WHERE session_id=? AND request_id=?", (session.id, job["request_id"]))

    def list(self):
        with self.connection() as conn:
            projects = [Project.model_validate_json(r["document"]) for r in conn.execute("SELECT document FROM projects")]
        result = []
        for p in projects:
            cards = [c for s in p.sessions for c in s.cards if c.status != "rejected"]
            result.append(dict(id=p.id,title=p.title,description=p.description,revision=p.revision,created_at=p.created_at,updated_at=p.updated_at,session_count=len(p.sessions),card_count=len(cards),question_count=sum(c.type == "question" for c in cards)))
        return sorted(result,key=lambda p:p["updated_at"],reverse=True)

    def create(self, new: NewProject):
        timestamp = now_iso()
        p = Project(id=str(uuid4()),title=new.title,description=new.description,revision=0,created_at=timestamp,updated_at=timestamp,sessions=[])
        with self.connection(write=True) as conn:
            conn.execute("INSERT INTO projects(id,revision,document) VALUES(?,?,?)", (p.id,0,p.model_dump_json()))
        return p

    def save(self, project_id, incoming: Project, expected_revision: int):
        if incoming.id != project_id or incoming.revision != expected_revision:
            raise StoreError("De identiteit of revisie van dit schetsboek klopt niet.",422)
        with self.connection(write=True) as conn:
            current = self._read(conn,project_id)
            if current.revision != expected_revision:
                raise StoreError("Dit schetsboek is intussen gewijzigd. Bewaar je lokale wijzigingen of laad de nieuwste versie.",409)
            updated = incoming.model_copy(update=dict(revision=current.revision+1,created_at=current.created_at,updated_at=now_iso()),deep=True)
            previous_sources = {segment.id: segment for session in current.sessions for segment in session.segments if segment.govern_source}
            for session in updated.sessions:
                for segment in session.segments:
                    if segment.id in previous_sources and segment != previous_sources[segment.id]:
                        raise StoreError("De Govern-bron blijft ongewijzigd. Schrijf je correctie in de eigen aantekeningen.", 422)
            previous_cards = {card.id: card for session in current.sessions for card in session.cards}
            for session in updated.sessions:
                for card in session.cards:
                    previous = previous_cards.get(card.id)
                    if previous and previous.proposal_key:
                        card.proposal_key = previous.proposal_key
            self._write(conn,updated)
        return updated

    def delete(self, project_id):
        with self.connection(write=True) as conn:
            self._read(conn,project_id)
            conn.execute("DELETE FROM projects WHERE id=?",(project_id,))

    def import_project(self, project: Project):
        mapping = {}
        def collect(value):
            if isinstance(value,dict):
                if "id" in value:
                    mapping[value["id"]] = str(uuid4())
                for child in value.values():
                    collect(child)
            elif isinstance(value,list):
                for child in value:
                    collect(child)
        def rekey(value,key=""):
            if isinstance(value,dict):
                return {field:(child if field == "request_id" and value.get("govern_source") else rekey(child, "edge_source" if field == "source" and "target" in value else field)) for field,child in value.items()}
            if isinstance(value,list):
                return [rekey(child,key) for child in value]
            if isinstance(value,str):
                if key == "request_id":
                    return str(uuid4())
                if key in {"id","edge_source","target","question_card_id","source_segment_ids"}:
                    return mapping.get(value,value)
            return value
        raw = project.model_dump()
        collect(raw)
        raw = rekey(raw)
        raw.update(revision=0,created_at=now_iso(),updated_at=now_iso())
        imported = Project.model_validate(raw)
        with self.connection(write=True) as conn:
            conn.execute("INSERT INTO projects(id,revision,document) VALUES(?,?,?)",(imported.id,0,imported.model_dump_json()))
            self._write(conn,imported)
        return imported

    def govern_page(self, project_id, identity, title):
        with self.connection(write=True) as conn:
            project = self._read(conn, project_id)
            page = next((s for s in project.sessions if s.govern_recording == identity), None)
            if page is None:
                page = Session(id=str(uuid4()), title=title[:160], source="govern", created_at=now_iso(), govern_recording=identity)
                project.sessions.append(page)
                project.revision += 1
                project.updated_at = now_iso()
                self._write(conn, project)
        return page.id

    def settings(self):
        with self.connection() as conn:
            return Settings.model_validate_json(conn.execute("SELECT document FROM settings WHERE id=1").fetchone()["document"])

    def save_settings(self,settings:Settings):
        with self.connection(write=True) as conn:
            conn.execute("UPDATE settings SET document=? WHERE id=1",(settings.model_dump_json(),))
        return settings

    def reserve_segment(self,session_id:str,body:TextInput,origin:str,organizer:str,govern_source=None):
        """Persist source before model work; failed work can be retried with the same request ID."""
        fingerprint = hashlib.sha256(body.text.encode()).hexdigest()
        with self.connection(write=True) as conn:
            project = self._session_project(conn,session_id)
            session = next(s for s in project.sessions if s.id==session_id)
            previous = next((s for s in session.segments if s.request_id==body.request_id),None)
            job = conn.execute("SELECT * FROM ingestion_jobs WHERE session_id=? AND request_id=?",(session_id,body.request_id)).fetchone()
            if previous:
                original_fingerprint = job["fingerprint"] if job else hashlib.sha256(previous.text.encode()).hexdigest()
                if original_fingerprint != fingerprint:
                    raise StoreError("Deze aanvraag-ID hoort al bij andere tekst.",409)
                if not job or job["state"]=="completed":
                    return project,previous,True
                conn.execute("UPDATE ingestion_jobs SET state='processing',organizer=? WHERE session_id=? AND request_id=?",(organizer,session_id,body.request_id))
                return project,previous,False
            segment = Segment(id=str(uuid4()),text=body.text,start_ms=body.start_ms,end_ms=body.end_ms,created_at=now_iso(),request_id=body.request_id,origin=origin,govern_source=govern_source)
            session.segments.append(segment)
            project.revision += 1
            project.updated_at = now_iso()
            self._write(conn,project)
            conn.execute("INSERT INTO ingestion_jobs(session_id,request_id,fragment_id,fingerprint,state,organizer) VALUES(?,?,?,?,?,?)",(session_id,body.request_id,segment.id,fingerprint,"processing",organizer))
        return project,segment,False

    def fail_job(self,session_id,request_id):
        with self.connection(write=True) as conn:
            conn.execute("UPDATE ingestion_jobs SET state='failed' WHERE session_id=? AND request_id=?",(session_id,request_id))

    def complete_segment(self,session_id,segment_id,request_id,candidates,extra_warnings=None):
        with self.connection(write=True) as conn:
            project = self._session_project(conn,session_id)
            session = next(s for s in project.sessions if s.id==session_id)
            segment = next((s for s in session.segments if s.id==segment_id),None)
            if not segment:
                raise StoreError("Het bronfragment is intussen verwijderd. Er zijn geen kaarten toegevoegd.",409)
            job = conn.execute("SELECT fingerprint FROM ingestion_jobs WHERE session_id=? AND request_id=?", (session_id,request_id)).fetchone()
            if job and job["fingerprint"] != hashlib.sha256(segment.text.encode()).hexdigest():
                candidates = []
                extra_warnings = list(extra_warnings or []) + ["Het bronfragment is tijdens het verwerken aangepast. Er zijn geen voorstellen uit de oude tekst toegevoegd."]
            signatures = {proposal_key(c.type,c.text or c.title) for c in session.cards}
            signatures.update(history_key(row["signature"]) for row in conn.execute("SELECT signature FROM proposal_history WHERE session_id=?", (session_id,)))
            prior_ids = {s.id for s in session.segments if s.id!=segment_id and normalize(s.text)==normalize(segment.text)}
            repeated = any(prior_ids.intersection(c.source_segment_ids) for c in session.cards)
            added,skipped = 0,0
            remaining_bytes = MAX_PROJECT_BYTES - project_size(project) - 100
            for candidate in candidates:
                if len(session.cards) >= 2000:
                    if extra_warnings is None:
                        extra_warnings = []
                    if "Het maximum van 2000 kaarten per sessie is bereikt; maak een nieuwe sessie." not in extra_warnings:
                        extra_warnings.append("Het maximum van 2000 kaarten per sessie is bereikt; maak een nieuwe sessie.")
                    break
                signature = proposal_key(candidate["type"],candidate["text"] or candidate["title"])
                if repeated or signature in signatures:
                    skipped += 1
                    continue
                for slot in range(3000):
                    position = dict(x=(slot%2)*320+(slot//400)*720,y=((slot%400)//2)*240)
                    if not any(abs(c.position.x-position["x"])<300 and abs(c.position.y-position["y"])<220 for c in session.cards if c.status!="rejected"):
                        break
                card = Card(id=str(uuid4()),status="proposal",manual=False,user_edited=False,proposal_key=signature,position=position,**candidate)
                card_bytes = len(card.model_dump_json().encode("utf-8")) + 1
                if card_bytes > remaining_bytes:
                    if extra_warnings is None:
                        extra_warnings = []
                    extra_warnings.append("De tekst is bewaard. Dit schetsboek is bijna vol; maak een nieuw schetsboek voor meer kaartvoorstellen.")
                    break
                remaining_bytes -= card_bytes
                session.cards.append(card)
                signatures.add(signature)
                added += 1
            if added:
                project.revision += 1
                project.updated_at = now_iso()
            self._write(conn,project)
            warnings = list(extra_warnings or [])
            if skipped:
                warnings.append("Eerder herkende tekst is niet opnieuw als kaart toegevoegd.")
            if not added and not warnings:
                warnings.append("De tekst is bewaard. Er zijn geen nieuwe kaartvoorstellen gevonden.")
            conn.execute("UPDATE ingestion_jobs SET state='completed',warnings=? WHERE session_id=? AND request_id=?",(json.dumps(warnings),session_id,request_id))
        return project,warnings

    def outcome(self,session_id,request_id):
        with self.connection() as conn:
            project = self._session_project(conn,session_id)
            row = conn.execute("SELECT organizer,warnings,state FROM ingestion_jobs WHERE session_id=? AND request_id=?",(session_id,request_id)).fetchone()
            if row and row["state"]=="completed":
                return project,row["organizer"],json.loads(row["warnings"])
        return None
