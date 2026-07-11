import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import voice_service
from voice_service import VoiceServiceHandler


class VoiceServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), VoiceServiceHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def get_json(self, path):
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=5) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, path, payload):
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read().decode("utf-8"))

    def test_health_reports_no_external_network_or_input_persistence(self):
        health = self.get_json("/health")
        self.assertEqual(health["status"], "ok")
        self.assertIn("sttProvider", health)
        self.assertIn("ttsProvider", health)
        self.assertEqual(health["externalNetworkCalled"], False)
        self.assertEqual(health["inputPersisted"], False)

    def test_mock_stt_returns_final_transcript_without_saving_audio(self):
        result = self.post_json(
            "/stt",
            {
                "requestId": "request-1",
                "sessionId": "session-1",
                "turnId": "turn-1",
                "streamId": "stream-1",
                "languageHint": "zh-CN",
                "audioBase64": "",
                "format": {"mimeType": "audio/webm", "sampleRateHz": 48000, "channels": 1},
            },
        )
        self.assertEqual(result["providerId"], "mock-stt")
        self.assertEqual(result["transcript"], "我选择左边的图片")
        self.assertGreater(result["confidence"], 0.9)
        self.assertEqual(result["externalNetworkCalled"], False)
        self.assertEqual(result["inputPersisted"], False)

    def test_mock_tts_returns_audio_without_saving_text(self):
        result = self.post_json(
            "/tts",
            {
                "requestId": "request-tts-1",
                "sessionId": "session-1",
                "turnId": "turn-1",
                "text": "我们继续做题吧。",
                "voice": "mock",
            },
        )
        self.assertEqual(result["providerId"], "mock-tts")
        self.assertEqual(result["mimeType"], "audio/wav")
        self.assertTrue(result["audioBase64"])
        self.assertEqual(result["externalNetworkCalled"], False)
        self.assertEqual(result["inputPersisted"], False)

    def test_local_piper_tts_returns_real_provider_audio_when_available(self):
        if not Path(voice_service.PIPER_MODEL_PATH).is_file() or not Path(voice_service.PIPER_CONFIG_PATH).is_file():
            self.skipTest("Local Piper model is not installed in the Git-ignored runtime directory.")
        try:
            import piper  # noqa: F401
        except Exception:  # noqa: BLE001
            self.skipTest("piper package is not installed in this Python environment.")

        previous_provider = voice_service.TTS_PROVIDER
        previous_voice = voice_service._piper_voice
        previous_error = voice_service._piper_error
        voice_service.TTS_PROVIDER = "local-piper"
        voice_service._piper_voice = None
        voice_service._piper_error = None
        try:
            result = self.post_json(
                "/tts",
                {
                    "requestId": "request-local-piper-1",
                    "sessionId": "session-1",
                    "turnId": "turn-1",
                    "text": "test",
                    "voice": "zh_CN-huayan-medium",
                },
            )
            self.assertEqual(result["providerId"], "local-piper-zh-huayan")
            self.assertEqual(result["modelId"], "zh_CN-huayan-medium")
            self.assertEqual(result["mimeType"], "audio/wav")
            self.assertTrue(result["audioBase64"].startswith("UklGR"))
            self.assertGreater(result["durationMs"], 0)
            self.assertEqual(result["externalNetworkCalled"], False)
            self.assertEqual(result["inputPersisted"], False)
        finally:
            voice_service.TTS_PROVIDER = previous_provider
            voice_service._piper_voice = previous_voice
            voice_service._piper_error = previous_error


if __name__ == "__main__":
    unittest.main()
