"""Optional model integrations are tested with bounded local HTTP fakes."""
import io
import json
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import httpx

from ghostsketch.adapters import AdapterError, LocalAdapters, MAX_UPLOAD_BYTES

REAL_CLIENT = httpx.Client
REAL_TEMP_DIR = tempfile.TemporaryDirectory


def wav_bytes(rate=16000, channels=1, milliseconds=1000):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b"\x00\x00" * (channels * rate * milliseconds // 1000))
    return stream.getvalue()


def mock_client(handler):
    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return REAL_CLIENT(*args, **kwargs)
    return patch("ghostsketch.adapters.httpx.Client", side_effect=factory)


class AdapterConfigurationTests(unittest.TestCase):
    def test_accepts_only_exact_loopback_http_service_origins(self):
        for value in ["http://127.0.0.1:11434", "http://localhost:9000/", "http://[::1]:8080"]:
            self.assertTrue(LocalAdapters(ollama_url=value).ollama_url.startswith("http://"))
        for value in [
            "https://localhost", "http://example.com", "http://127.0.0.1.evil.invalid",
            "http://localhost/path", "http://user@localhost", "http://localhost?",
            "http://localhost#", "http://localhost:0", "http://localhost:70000",
            "http://local\nhost:80", "file:///tmp/model", "http://localhost./", "http://2130706433",
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                LocalAdapters(ollama_url=value)
        with self.assertRaises(ValueError):
            LocalAdapters(whisper_url="http://external.invalid")

    def test_capabilities_probe_known_local_paths_and_installed_models(self):
        seen = []
        def handler(request):
            seen.append(str(request.url))
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "small:latest"}, {"name": "small:latest"}, {"bad": "ignored"}]})
            return httpx.Response(200, json={"status": "ok"})
        with mock_client(handler), patch("ghostsketch.adapters.shutil.which", return_value="/bin/ffmpeg"):
            result = LocalAdapters(whisper_url="http://127.0.0.1:8080").capabilities()
        self.assertEqual(result, {"ollama_available": True, "ollama_models": ["small:latest"], "speech_available": True, "audio_conversion_available": True})
        self.assertEqual(seen, ["http://127.0.0.1:11434/api/tags", "http://127.0.0.1:8080/health"])

    def test_absent_services_report_capabilities_without_crashing(self):
        def handler(request):
            raise httpx.ConnectError("offline", request=request)
        with mock_client(handler), patch("ghostsketch.adapters.shutil.which", return_value=None):
            result = LocalAdapters(whisper_url="http://localhost:8080").capabilities()
        self.assertFalse(result["ollama_available"])
        self.assertFalse(result["speech_available"])
        self.assertEqual(result["ollama_models"], [])

    def test_redirect_is_not_followed(self):
        requests = []
        def handler(request):
            requests.append(str(request.url))
            return httpx.Response(302, headers={"location": "http://external.invalid/"})
        with mock_client(handler), self.assertRaises(AdapterError):
            LocalAdapters._request_json("GET", "http://localhost/api/tags")
        self.assertEqual(len(requests), 1)


class OrganizerAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = LocalAdapters()
        self.card = {"type": "question", "title": "Werkt Unity vanaf SSD?", "text": "Nog uitzoeken.", "source_segment_ids": ["segment-1"]}

    def response_handler(self, content):
        return lambda request: httpx.Response(200, json={"message": {"content": content}})

    def test_structured_request_and_valid_source_linked_output(self):
        seen = []
        def handler(request):
            payload = json.loads(request.read())
            seen.append(payload)
            return httpx.Response(200, json={"message": {"content": json.dumps({"cards": [self.card]})}})
        with mock_client(handler):
            cards = self.adapter.organize("Werkt Unity vanaf SSD?", "small:latest", "segment-1", "a" * 20000)
        self.assertEqual(cards, [self.card])
        payload = seen[0]
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["options"]["temperature"], 0)
        source = json.loads(payload["messages"][1]["content"])
        self.assertEqual(len(source["context"]), 3000)
        self.assertEqual(source["fragment_id"], "segment-1")
        self.assertEqual(payload["format"]["properties"]["cards"]["maxItems"], 20)
        self.assertEqual(payload["format"]["properties"]["cards"]["items"]["properties"]["title"]["maxLength"], 120)

    def test_rejects_malformed_excess_or_fabricated_model_fields(self):
        wrong_source = {**self.card, "source_segment_ids": ["invented-id"]}
        invalid_cards = [
            "not json", json.dumps({"cards": [wrong_source]}),
            json.dumps({"cards": [{**self.card, "command": "ignored"}]}),
            json.dumps({"cards": [self.card] * 21}),
            json.dumps({"cards": [{**self.card, "type": "fact"}]}),
            json.dumps({"cards": [{**self.card, "title": True}]}),
            json.dumps({"cards": [{**self.card, "title": " "}]}),
            json.dumps({"cards": [{**self.card, "title": "x" * 121}]}),
            json.dumps({"cards": [], "extra": True}),
            json.dumps({"cards": [{**self.card, "source_segment_ids": "segment-1"}]}),
        ]
        for content in invalid_cards:
            with self.subTest(content=content[:100]), mock_client(self.response_handler(content)), self.assertRaises(AdapterError) as error:
                self.adapter.organize("Vraag", "small", "segment-1")
            self.assertEqual(error.exception.status_code, 502)

    def test_empty_model_or_long_text_is_rejected_before_call(self):
        with patch.object(self.adapter, "_request_json") as request:
            for text, model in [("Hallo", ""), ("a" * 16001, "small")]:
                with self.assertRaises(AdapterError) as error:
                    self.adapter.organize(text, model, "segment-1")
                self.assertEqual(error.exception.status_code, 422)
            request.assert_not_called()

    def test_http_connection_json_and_response_budget_errors(self):
        cases = [
            (lambda request: httpx.Response(404, json={"error": "model absent"}), 502),
            (lambda request: httpx.Response(200, content=b"not-json"), 502),
            (lambda request: httpx.Response(200, content=b"a" * (512 * 1024 + 1)), 502),
        ]
        for handler, status in cases:
            with mock_client(handler), self.assertRaises(AdapterError) as error:
                self.adapter.organize("Vraag", "small", "segment-1")
            self.assertEqual(error.exception.status_code, status)


class AudioAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = LocalAdapters(whisper_url="http://127.0.0.1:8080")

    def test_wav_transcription_uses_multipart_and_deletes_temporary_audio(self):
        paths = []
        def request(method, url, **kwargs):
            self.assertEqual(url, "http://127.0.0.1:8080/inference")
            name, file, mime = kwargs["files"]["file"]
            self.assertEqual((name, mime), ("speech.wav", "audio/wav"))
            self.assertEqual(kwargs["data"]["language"], "nl")
            self.assertEqual(kwargs["data"]["response_format"], "json")
            paths.append(Path(file.name))
            self.assertTrue(paths[0].exists())
            self.assertEqual(file.read(4), b"RIFF")
            return {"text": " Een lokaal gesprek. "}
        with patch.object(self.adapter, "_request_json", side_effect=request):
            result = self.adapter.transcribe(wav_bytes(), "../notes.wav")
        self.assertEqual(result, ("Een lokaal gesprek.", 1000))
        self.assertFalse(paths[0].exists())
        self.assertFalse(paths[0].parent.exists())

    def test_real_http_multipart_encoding_with_local_fake(self):
        seen = []
        def handler(request):
            body = request.read()
            self.assertEqual(request.url.path, "/inference")
            self.assertIn("multipart/form-data; boundary=", request.headers["content-type"])
            self.assertIn(b'name="file"; filename="speech.wav"', body)
            self.assertIn(b'name="language"', body)
            self.assertIn(b"RIFF", body)
            seen.append(request)
            return httpx.Response(200, json={"text": "Echt gecodeerde multipart."})
        with mock_client(handler):
            self.assertEqual(self.adapter.transcribe(wav_bytes(), "test.wav"), ("Echt gecodeerde multipart.", 1000))
        self.assertEqual(len(seen), 1)

    def test_audio_cleanup_on_service_error(self):
        paths = []
        def fail(method, url, **kwargs):
            paths.append(Path(kwargs["files"]["file"][1].name))
            raise AdapterError("Niet bereikbaar", 503)
        with patch.object(self.adapter, "_request_json", side_effect=fail), self.assertRaises(AdapterError):
            self.adapter.transcribe(wav_bytes(), "voice.wav")
        self.assertFalse(paths[0].parent.exists())

    def test_codec_conversion_is_bounded_and_cleaned(self):
        seen = []
        def convert(command, **kwargs):
            seen.append(command)
            self.assertIs(command.__class__, list)
            self.assertEqual(kwargs["timeout"], 90)
            self.assertEqual(command[command.index("-protocol_whitelist") + 1], "file,pipe")
            Path(command[-1]).write_bytes(wav_bytes())
            return subprocess.CompletedProcess(command, 0)
        paths = []
        def request(method, url, **kwargs):
            paths.append(Path(kwargs["files"]["file"][1].name))
            return {"text": "Omgezette opname"}
        with patch("ghostsketch.adapters.shutil.which", return_value="ffmpeg"), patch("ghostsketch.adapters.subprocess.run", side_effect=convert), patch.object(self.adapter, "_request_json", side_effect=request):
            self.assertEqual(self.adapter.transcribe(b"encoded", "../../recording.m4a"), ("Omgezette opname", 1000))
        self.assertEqual(seen[0][seen[0].index("-f") + 1], "mov")
        self.assertFalse(paths[0].parent.exists())

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is optional")
    def test_real_ffmpeg_resamples_stereo_wav(self):
        def request(method, url, **kwargs):
            with wave.open(kwargs["files"]["file"][1], "rb") as audio:
                self.assertEqual((audio.getnchannels(), audio.getframerate(), audio.getsampwidth()), (1, 16000, 2))
            return {"text": "Stereo is lokaal omgezet."}
        with patch.object(self.adapter, "_request_json", side_effect=request):
            result = self.adapter.transcribe(wav_bytes(rate=48000, channels=2), "stereo.wav")
        self.assertEqual(result, ("Stereo is lokaal omgezet.", 1000))

    def test_conversion_failure_cleans_up_files(self):
        with REAL_TEMP_DIR() as root:
            factory = lambda **kwargs: REAL_TEMP_DIR(dir=root, **kwargs)
            with patch("ghostsketch.adapters.tempfile.TemporaryDirectory", side_effect=factory), patch("ghostsketch.adapters.shutil.which", return_value="ffmpeg"), patch("ghostsketch.adapters.subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 90)):
                with self.assertRaises(AdapterError) as error:
                    self.adapter.transcribe(b"encoded", "recording.m4a")
                self.assertEqual(error.exception.status_code, 422)
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_upload_and_codec_failures(self):
        self.assertEqual(MAX_UPLOAD_BYTES, 25 * 1024 * 1024)
        with patch("ghostsketch.adapters.MAX_UPLOAD_BYTES", 4), self.assertRaises(AdapterError) as error:
            self.adapter.transcribe(b"12345", "a.wav")
        self.assertEqual(error.exception.status_code, 413)
        with self.assertRaises(AdapterError) as error:
            LocalAdapters().transcribe(b"123", "a.wav")
        self.assertEqual(error.exception.status_code, 503)
        for name, content in [("file.txt", b"hello"), ("file.wav", b"bad-wave"), ("file.m4a", b"encoded"), ("file.wav", b"")]:
            with self.subTest(name=name), patch("ghostsketch.adapters.shutil.which", return_value=None), self.assertRaises(AdapterError) as error:
                self.adapter.transcribe(content, name)
            self.assertEqual(error.exception.status_code, 422)

    def test_malformed_response_rejected_and_silence_not_fabricated(self):
        for data in [{}, {"text": 5}, {"text": "content", "error": "invalid"}]:
            with patch.object(self.adapter, "_request_json", return_value=data), self.assertRaises(AdapterError) as error:
                self.adapter.transcribe(wav_bytes(), "voice.wav")
            self.assertEqual(error.exception.status_code, 502)
        with patch.object(self.adapter, "_request_json", return_value={"text": "  "}):
            self.assertEqual(self.adapter.transcribe(wav_bytes(), "voice.wav"), ("", 1000))


if __name__ == "__main__":
    unittest.main()
