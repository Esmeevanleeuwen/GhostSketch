"""Real HTTP/SQLite tests; optional model servers are replaced at the boundary."""
import copy
import tempfile
from pathlib import Path
from unittest import TestCase

from fastapi.testclient import TestClient

from ghostsketch.adapters import AdapterError
from ghostsketch.app import create_app
from ghostsketch.models import now_iso
from storage_fixture import StorageFixture


class FakeAdapters:
    def __init__(self):
        self.calls = 0
        self.audio_calls = 0
        self.failure = False
        self.transcript = "We moeten morgen het prototype testen."
        self.during_organize = None

    def capabilities(self):
        return dict(ollama_available=True, ollama_models=["local:test"], speech_available=True, audio_conversion_available=False)

    def organize(self, text, model, segment_id, context=""):
        self.calls += 1
        if self.during_organize:
            self.during_organize()
        if self.failure:
            raise AdapterError("Het lokale taalmodel is niet bereikbaar.")
        return [dict(type="idea", title="Voorstel", text=text[:2000], source_segment_ids=[segment_id])]

    def transcribe(self, content, filename):
        self.audio_calls += 1
        if self.failure:
            raise AdapterError("Spraakdienst niet bereikbaar.")
        return self.transcript, 8000


class ApiTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.adapters = FakeAdapters()
        self.storage = StorageFixture()
        self.app = create_app(self.directory.name, self.adapters, govern=self.storage.source)
        self.client = TestClient(self.app, base_url="http://localhost:8000")
        self.headers = {"X-GhostSketch-Token": self.client.get("/api/bootstrap").json()["token"]}

    def tearDown(self):
        self.client.close()
        self.directory.cleanup()

    def post(self, path, data):
        return self.client.post(path, json=data, headers=self.headers)

    def put(self, project):
        return self.client.put("/api/projects/" + project["id"], json={"expected_revision": project["revision"], "project": project}, headers=self.headers)

    def project(self, source="text"):
        project = self.post("/api/projects", {"title": "Mijn schetsboek"}).json()
        project["sessions"] = [dict(id="session-one", title="Gesprek", source=source, created_at=now_iso(), ended_at=None, segments=[], cards=[], edges=[], research_jobs=[])]
        response = self.put(project)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def segment(self, text="Misschien kunnen we een houten voet maken.", request_id="request-one"):
        return self.post("/api/sessions/session-one/segments", dict(text=text, request_id=request_id))

    def settings_ollama(self):
        response = self.client.put("/api/settings", json=dict(organizer="ollama", ollama_model="local:test", language="nl", recordings_retained=False), headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)

    def test_empty_installation_and_restart_persistence(self):
        self.assertEqual(self.client.get("/api/projects").json(), [])
        p = self.project()
        second = create_app(self.directory.name, FakeAdapters())
        with TestClient(second, base_url="http://localhost:8000") as other:
            self.assertEqual(other.get("/api/projects/" + p["id"]).json(), p)
            self.assertNotEqual(second.state.token, self.app.state.token)

    def test_stale_revision_is_409_without_overwrite(self):
        p = self.project()
        stale = copy.deepcopy(p)
        p["title"] = "Opgeslagen titel"
        current = self.put(p).json()
        stale["title"] = "Verouderde titel"
        self.assertEqual(self.put(stale).status_code, 409)
        self.assertEqual(self.client.get("/api/projects/" + p["id"]).json(), current)

    def test_token_host_origin_and_foreign_preflight_rejected(self):
        self.assertEqual(self.client.post("/api/projects", json={"title": "x"}).status_code, 403)
        self.assertEqual(self.client.get("/api/bootstrap", headers={"host": "attacker.example"}).status_code, 403)
        self.assertEqual(self.client.get("/api/bootstrap", headers={"origin": "https://attacker.example"}).status_code, 403)
        self.assertEqual(self.client.options("/api/projects", headers={"origin": "https://attacker.example"}).status_code, 403)
        self.assertEqual(self.client.get("/api/bootstrap", headers={"origin": "http://localhost:5173"}).status_code, 200)
        self.assertNotIn("access-control-allow-origin", self.client.get("/api/bootstrap").headers)

    def test_refs_duplicate_ids_invalid_timestamp_and_unsafe_urls(self):
        p = self.project()
        bad = copy.deepcopy(p)
        for invalid_date in ["abcdefghij", "2026-02-30T10:00:00Z", "2026-11-05T10:00:00", "2026-11-05T10:00:00+01:00:30"]:
            bad["created_at"] = invalid_date
            self.assertEqual(self.put(bad).status_code, 422)
        bad = copy.deepcopy(p)
        bad["sessions"][0]["id"] = p["id"]
        self.assertEqual(self.put(bad).status_code, 422)
        bad = copy.deepcopy(p)
        bad["sessions"][0]["cards"] = [dict(id="card-x", type="question", title="Waarom?", text="Waarom?", status="proposal", source_segment_ids=["missing"], manual=False, user_edited=False, position={"x": 0,"y": 0})]
        self.assertEqual(self.put(bad).status_code, 422)
        self.assertEqual(self.client.get("/api/projects/" + p["id"]).json(), p)

    def test_text_original_preserved_and_idempotent_after_restart(self):
        self.project()
        original = "Misschien kunnen we een houten voet maken.\nWaarom is de basis zo zwaar?"
        result = self.segment(original).json()
        self.assertEqual(result["organizer"], "rules")
        session = result["project"]["sessions"][0]
        self.assertEqual(session["segments"][0]["text"], original)
        self.assertEqual({c["type"] for c in session["cards"]}, {"idea", "question"})
        again = self.segment(original).json()
        self.assertEqual(again, result)
        self.assertEqual(self.segment("Andere tekst").status_code, 409)
        with TestClient(create_app(self.directory.name, FakeAdapters()), base_url="http://localhost:8000") as restarted:
            token = restarted.get("/api/bootstrap").json()["token"]
            r = restarted.post("/api/sessions/session-one/segments", json={"text": original,"request_id": "request-one"}, headers={"X-GhostSketch-Token": token})
            self.assertEqual(r.json(), result)

    def test_ollama_failure_preserves_text_and_confirmed_warning_without_retry(self):
        self.project()
        self.settings_ollama()
        self.adapters.failure = True
        response = self.segment()
        self.assertEqual(response.status_code, 200, response.text)
        outcome = response.json()
        self.assertTrue(outcome["warnings"])
        session = outcome["project"]["sessions"][0]
        self.assertEqual(len(session["segments"]), 1)
        self.assertEqual(session["cards"], [])
        self.adapters.failure = False
        self.assertEqual(self.segment().json(), outcome)
        self.assertEqual(self.adapters.calls, 1)

    def test_ollama_valid_and_malformed_output(self):
        self.project()
        self.settings_ollama()
        valid = self.segment().json()
        self.assertEqual(len(valid["project"]["sessions"][0]["cards"]), 1)
        self.adapters.organize = lambda *args: [{"type": "idea", "title": "onveilig", "text": "x", "source_segment_ids": ["wrong-id"]}]
        invalid = self.segment("Nieuwe idee tekst.", "request-two").json()
        self.assertTrue(invalid["warnings"])
        self.assertEqual(len(invalid["project"]["sessions"][0]["cards"]), 1)
        self.assertEqual(len(invalid["project"]["sessions"][0]["segments"]), 2)

    def test_rejected_and_edited_cards_stay_unchanged(self):
        self.project()
        p = self.segment().json()["project"]
        card = p["sessions"][0]["cards"][0]
        card.update(title="Mijn eigen titel", text="Mijn aangepaste tekst", user_edited=True, status="rejected", position={"x": 123,"y": 456})
        p = self.put(p).json()
        next_p = self.segment(request_id="request-two").json()["project"]
        self.assertEqual(next_p["sessions"][0]["cards"], p["sessions"][0]["cards"])
        self.assertEqual(len(next_p["sessions"][0]["segments"]), 2)

    def test_model_work_preserves_concurrent_manual_edit(self):
        self.project()
        p = self.segment().json()["project"]
        self.settings_ollama()
        def edit():
            latest = self.app.state.store.get(p["id"])
            latest.sessions[0].cards[0].title = "Tijdens modelverzoek gewijzigd"
            latest.sessions[0].cards[0].user_edited = True
            self.app.state.store.save(latest.id, latest, latest.revision)
        self.adapters.during_organize = edit
        result = self.segment("Nieuw idee voor een ronde vorm.", "request-two").json()
        self.assertEqual(result["project"]["sessions"][0]["cards"][0]["title"], "Tijdens modelverzoek gewijzigd")
        self.assertEqual(len(result["project"]["sessions"][0]["cards"]), 2)

    def test_import_rekeys_all_ids_and_keeps_relations(self):
        self.project()
        p = self.segment("Waarom is de voet zwaar? Misschien kunnen we een houten voet maken.").json()["project"]
        session = p["sessions"][0]
        question = next(c for c in session["cards"] if c["type"] == "question")
        other = next(c for c in session["cards"] if c["type"] == "idea")
        session["edges"] = [dict(id="edge-one", source=question["id"], target=other["id"], label="leidt tot", origin="manual")]
        session["research_jobs"] = [dict(id="job-one", question_card_id=question["id"], query="houten voet", status="documented", approved_at=now_iso(), sources=[dict(id="source-one", title="Bron", url="https://example.org/article", excerpt="Letterlijke bron", retrieved_at=now_iso())])]
        response = self.post("/api/projects/import", p)
        self.assertEqual(response.status_code, 200, response.text)
        imported = response.json()
        self.assertNotEqual(imported["id"], p["id"])
        self.assertEqual(imported["revision"], 0)
        s = imported["sessions"][0]
        self.assertNotEqual(s["id"], session["id"])
        self.assertEqual(s["source"], "text")
        self.assertEqual(s["cards"][0]["source_segment_ids"], [s["segments"][0]["id"]])
        self.assertEqual(s["edges"][0]["source"], next(c["id"] for c in s["cards"] if c["type"] == "question"))
        self.assertEqual(s["research_jobs"][0]["question_card_id"], s["edges"][0]["source"])
        p["created_at"] = "not a valid timestamp"
        self.assertEqual(self.post("/api/projects/import", p).status_code, 422)

    def test_audio_failure_no_mutation_and_valid_idempotent_transcript(self):
        p = self.project("microphone")
        self.adapters.failure = True
        args = dict(data={"request_id": "audio-one"}, files={"file": ("part.wav", b"placeholder", "audio/wav")}, headers=self.headers)
        self.assertEqual(self.client.post("/api/sessions/session-one/audio", **args).status_code, 503)
        self.assertEqual(self.client.get("/api/projects/" + p["id"]).json(), p)
        self.adapters.failure = False
        result = self.client.post("/api/sessions/session-one/audio", **args)
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        segment = body["project"]["sessions"][0]["segments"][0]
        self.assertEqual(segment["origin"], "microphone")
        self.assertEqual(segment["end_ms"], 8000)
        self.assertEqual(self.client.post("/api/sessions/session-one/audio", **args).json(), body)
        self.assertEqual(self.adapters.audio_calls, 2)

    def test_silence_does_not_create_empty_source_or_cards(self):
        p = self.project("audio")
        self.adapters.transcript = ""
        result = self.client.post("/api/sessions/session-one/audio", data={"request_id": "silent"}, files={"file": ("silence.wav", b"data", "audio/wav")}, headers=self.headers).json()
        self.assertEqual(result["project"], p)
        self.assertTrue(result["warnings"])

    def test_validation_limits_and_setting_privacy(self):
        self.project()
        self.assertEqual(self.segment(" ").status_code, 422)
        self.assertEqual(self.segment("x" * 50001).status_code, 422)
        self.assertEqual(self.segment(request_id="bad request").status_code, 422)
        self.assertEqual(self.post("/api/sessions/session-one/segments", {"text": "x", "request_id": "new", "start_ms": 8,"end_ms": 4}).status_code, 422)
        self.assertEqual(self.client.put("/api/settings", json={"organizer": "ollama", "ollama_model": ""}, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.put("/api/settings", json={"recordings_retained": True}, headers=self.headers).status_code, 422)
        r = self.client.post("/api/projects", content=b"{}", headers={**self.headers, "Content-Type": "application/json", "Content-Length": str(9 * 1024 * 1024)})
        self.assertEqual(r.status_code, 413)

    def test_spa_assets_and_unknown_api_are_separate(self):
        assets = Path(self.directory.name) / "dist"
        assets.mkdir()
        (assets / "index.html").write_text("<html>GhostSketch</html>")
        (assets / "bundle.js").write_text("window.ghost = true;")
        with TestClient(create_app(Path(self.directory.name) / "other", self.adapters, assets), base_url="http://localhost:8000") as client:
            self.assertIn("GhostSketch", client.get("/projects/example").text)
            self.assertIn("window.ghost", client.get("/bundle.js").text)
            self.assertEqual(client.get("/api/unknown").status_code, 404)
            self.assertEqual(client.get("/api/unknown").json()["detail"], "Deze API-route bestaat niet.")

    def test_full_bounded_audio_transcript_is_preserved(self):
        self.project("microphone")
        original = "Een gespreksfragment. " * 3000
        self.assertGreater(len(original), 50000)
        self.adapters.transcript = original
        result = self.client.post("/api/sessions/session-one/audio", data={"request_id": "long-audio"}, files={"file": ("speech.wav", b"data", "audio/wav")}, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["project"]["sessions"][0]["segments"][0]["text"], original)

    def test_unexpected_organizer_failure_still_confirms_preserved_source(self):
        self.project()
        self.settings_ollama()
        def unexpected(*args):
            raise RuntimeError("Unexpected adapter fault")
        self.adapters.organize = unexpected
        with self.assertLogs("ghostsketch", level="ERROR"):
            response = self.segment()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["project"]["sessions"][0]["segments"]), 1)
        self.assertTrue(response.json()["warnings"])
        self.assertEqual(response.json()["project"]["sessions"][0]["cards"], [])

    def test_changed_source_during_model_work_never_gets_old_proposals(self):
        p = self.project()
        self.settings_ollama()
        def edit_source():
            latest = self.app.state.store.get(p["id"])
            latest.sessions[0].segments[0].text = "We besluiten voorlopig geen houten voet te maken."
            self.app.state.store.save(latest.id, latest, latest.revision)
        self.adapters.during_organize = edit_source
        response = self.segment()
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["project"]["sessions"][0]["cards"], [])
        self.assertTrue(result["warnings"])
        self.assertIn("geen houten voet", result["project"]["sessions"][0]["segments"][0]["text"])
        self.assertEqual(self.segment().json(), result)

    def test_edited_rejected_proposal_not_reintroduced_by_different_fragment_boundary(self):
        self.project()
        p = self.segment("Kan Unity op een SSD? We moeten morgen testen.").json()["project"]
        card = next(c for c in p["sessions"][0]["cards"] if c["type"] == "question")
        card.update(title="Mijn aangepaste vraag", text="Een aangepaste vraag", user_edited=True, status="rejected")
        saved = self.put(p).json()
        result = self.segment("Kan Unity op een SSD?", "request-two").json()
        self.assertEqual(result["project"]["sessions"][0]["cards"], saved["sessions"][0]["cards"])
        self.assertTrue(result["warnings"])

    def test_many_existing_cards_keep_new_position_within_valid_bounds(self):
        p = self.project()
        p["sessions"][0]["cards"] = [dict(id=f"card-{i}", type="idea", title=f"Kaart {i}", text=f"Bestaande kaart {i}", status="accepted", source_segment_ids=[], manual=True, user_edited=False, position={"x": (i%3)*320, "y": (i//3)*240}) for i in range(1251)]
        response = self.put(p)
        self.assertEqual(response.status_code, 200, response.text)
        p = response.json()
        result = self.segment().json()
        cards = result["project"]["sessions"][0]["cards"]
        self.assertEqual(len(cards), 1252)
        self.assertLessEqual(abs(cards[-1]["position"]["y"]), 100000)
        self.assertEqual(cards[:-1], p["sessions"][0]["cards"])

    def test_project_size_limit_keeps_last_confirmed_snapshot_editable_and_importable(self):
        p = self.project()
        timestamp = now_iso()
        p["sessions"][0]["segments"] = [dict(id=f"segment-{i}", text="x"*50000, start_ms=0, end_ms=0, created_at=timestamp, request_id=f"old-request-{i}", origin="text") for i in range(145)]
        first = self.put(p)
        self.assertEqual(first.status_code, 200, first.text[:500])
        latest = first.json()
        for i in range(4):
            response = self.segment("y"*50000, f"large-request-{i}")
            if response.status_code == 413:
                break
            self.assertEqual(response.status_code, 200, response.text[:500])
            latest = response.json()["project"]
        else:
            self.fail("Ingestion exceeded the project budget without rejection")
        self.assertEqual(self.client.get("/api/projects/" + p["id"]).json(), latest)
        latest["title"] = "Nog steeds bewerkbaar"
        saved = self.put(latest)
        self.assertEqual(saved.status_code, 200, saved.text[:500])
        imported = self.post("/api/projects/import", saved.json())
        self.assertEqual(imported.status_code, 200, imported.text[:500])

    def test_research_needs_question_and_safe_real_source_url(self):
        self.project()
        p = self.segment("Waarom is de voet zwaar? We moeten morgen testen.").json()["project"]
        session = p["sessions"][0]
        question = next(c for c in session["cards"] if c["type"] == "question")
        action = next(c for c in session["cards"] if c["type"] == "action")
        job = dict(id="research-one", question_card_id=question["id"], query="materiaal voet", status="documented", approved_at=now_iso(), sources=[dict(id="source-one", title="Mijn bron", url="javascript:alert(1)", excerpt="Geciteerd fragment", retrieved_at=now_iso())])
        session["research_jobs"] = [job]
        self.assertEqual(self.put(p).status_code, 422)
        job["sources"][0]["url"] = "https://user:secret@example.org/"
        self.assertEqual(self.put(p).status_code, 422)
        job["sources"][0]["url"] = "https://example.org/article"
        job["question_card_id"] = action["id"]
        self.assertEqual(self.put(p).status_code, 422)
        job["question_card_id"] = question["id"]
        job["approved_at"] = None
        self.assertEqual(self.put(p).status_code, 422)
        job["approved_at"] = now_iso()
        self.assertEqual(self.put(p).status_code, 200)

    def test_audio_upload_over_limit_does_not_modify_project(self):
        p = self.project("audio")
        response = self.client.post("/api/sessions/session-one/audio", data={"request_id": "oversized"}, files={"file": ("large.wav", b"0" * (25 * 1024 * 1024 + 1), "audio/wav")}, headers=self.headers)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.adapters.audio_calls, 0)
        self.assertEqual(self.client.get("/api/projects/" + p["id"]).json(), p)

    def test_proposal_protection_survives_export_import(self):
        self.project()
        p = self.segment("Kan Unity op een SSD? We moeten morgen testen.").json()["project"]
        question = next(c for c in p["sessions"][0]["cards"] if c["type"] == "question")
        original_key = question["proposal_key"]
        self.assertEqual(len(original_key), 64)
        question.update(title="Mijn aangepaste vraag", text="Mijn eigen tekst", user_edited=True, status="rejected")
        # A stale client omitting optional metadata cannot erase its provenance.
        question.pop("proposal_key")
        saved = self.put(p).json()
        saved_question = next(c for c in saved["sessions"][0]["cards"] if c["type"] == "question")
        self.assertEqual(saved_question["proposal_key"], original_key)
        imported_response = self.post("/api/projects/import", saved)
        self.assertEqual(imported_response.status_code, 200, imported_response.text)
        imported = imported_response.json()
        session = imported["sessions"][0]
        response = self.post(f'/api/sessions/{session["id"]}/segments', {"text": "Kan Unity op een SSD?", "request_id": "new-boundary"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["project"]["sessions"][0]["cards"], session["cards"])
        self.assertTrue(response.json()["warnings"])

    def test_first_four_proposals_form_two_readable_columns(self):
        self.project()
        result = self.segment("Misschien kunnen we hout gebruiken. Waarom is de voet zwaar? We moeten morgen testen. We besluiten: eerst een prototype.").json()
        cards = result["project"]["sessions"][0]["cards"]
        self.assertEqual(len(cards), 4)
        self.assertEqual([card["position"] for card in cards], [{"x":0,"y":0},{"x":320,"y":0},{"x":0,"y":240},{"x":320,"y":240}])
