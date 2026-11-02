import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import traduz_local as translator


class TranslationRegressionTests(unittest.TestCase):
    batch = [{"id": 7, "text": "Merhaba."}]

    def response(self, content, **extra):
        return io.BytesIO(json.dumps({"content": content, **extra}).encode())

    def test_aya_bypasses_chat_parser_and_constrains_json(self):
        result = '{"subtitles":[{"id":7,"text":"Olá."}]}'
        with patch.object(translator, "MODEL", "aya-23-8b-local"), patch.object(
            translator.urllib.request, "urlopen", return_value=self.response(result)
        ) as http:
            self.assertEqual(translator.request_batch([], self.batch), {7: "Olá."})
        request = http.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/completion"))
        self.assertNotIn("/chat/", request.full_url)
        payload = json.loads(request.data)
        self.assertNotIn("messages", payload)
        self.assertNotIn("response_format", payload)
        self.assertTrue(payload["prompt"].startswith("<BOS_TOKEN><|START_OF_TURN_TOKEN|>"))
        self.assertTrue(payload["prompt"].endswith("<|CHATBOT_TOKEN|>"))
        self.assertIn("Merhaba.", payload["prompt"])
        self.assertEqual(payload["json_schema"]["required"], ["subtitles"])
        items = payload["json_schema"]["properties"]["subtitles"]["items"]
        self.assertEqual(items["properties"]["id"]["enum"], [7])

    def test_other_models_keep_chat_endpoint(self):
        response = {"choices": [{"message": {"content":
                    '{"subtitles":[{"id":7,"text":"Olá."}]}'}, "finish_reason": "stop"}]}
        with patch.object(translator, "MODEL", "qwen3-8b-local"), patch.object(
            translator.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(response).encode())
        ) as http:
            self.assertEqual(translator.request_batch([], self.batch), {7: "Olá."})
        self.assertTrue(http.call_args.args[0].full_url.endswith("/chat/completions"))
        self.assertIn("schema", json.loads(http.call_args.args[0].data)["response_format"])

    def test_unrelated_package_and_ambiguous_lists_are_rejected(self):
        bad_results = [
            {"name": "command-r", "keywords": ["random"]},
            {"subtitles": ["Olá."]},
            {"subtitles": [{"text": "Olá."}]},
            {"subtitles": [{"id": 7, "text": " "}]},
            {"subtitles": [{"id": 7, "text": {"invalid": True}}]},
            {"subtitles": [{"id": 7, "text": "Olá."}, {"id": 7, "text": "Olá."}]},
        ]
        for result in bad_results:
            with self.subTest(result=result), self.assertRaises(ValueError):
                translator.extract_translations(result, self.batch)

    def test_peg_failure_stops_without_retrying_all_subtitles(self):
        error = urllib.error.HTTPError("http://localhost", 500, "Internal Server Error", {},
            io.BytesIO(b'{"error":{"message":"does not match the expected peg-native format"}}'))
        with patch.object(translator.urllib.request, "urlopen", side_effect=error) as http:
            with self.assertRaises(translator.LocalServerConfigurationError):
                translator.translate_batch_with_fallbacks([], self.batch * 12)
        self.assertEqual(http.call_count, 1)

    def test_native_truncation_is_rejected_even_with_parseable_json(self):
        content = '{"subtitles":[{"id":7,"text":"Olá."}]}'
        with patch.object(translator, "MODEL", "aya-23-8b-local"), patch.object(
            translator.urllib.request, "urlopen", return_value=self.response(content, stopped_limit=True)
        ), self.assertRaisesRegex(ValueError, "truncada"):
            translator.request_batch([], self.batch)

    def test_failed_translation_never_becomes_source_text(self):
        with patch.object(translator, "request_batch", side_effect=ValueError("invalid JSON")), patch.object(
            translator.time, "sleep"
        ), self.assertRaisesRegex(RuntimeError, "fala 7"):
            translator.translate_batch_with_fallbacks([], self.batch)

    def test_failure_preserves_previous_checkpoint_and_does_not_publish_shard(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.srt"
            output = Path(directory) / "part.json"
            source.write_text("1\n00:00:01,000 --> 00:00:02,000\nMerhaba.\n\n"
                              "2\n00:00:03,000 --> 00:00:04,000\nGünaydın.\n")
            argv = ["traduz_local.py", str(source), str(output), "-b", "1",
                    "--parts", "1", "--part-index", "0", "--partial-json"]
            with patch("sys.argv", argv), patch.object(translator, "translate_batch_with_fallbacks",
                    side_effect=[{1: "Olá."}, RuntimeError("failed")]), self.assertRaises(RuntimeError):
                translator.main()
            self.assertFalse(output.exists())
            checkpoint = json.loads(output.with_suffix(".ckpt.json").read_text())
            self.assertEqual(checkpoint["translations"], {"1": "Olá."})


if __name__ == "__main__":
    unittest.main()
