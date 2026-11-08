import tempfile
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import media_cli
from gerar_versoes_legendas import strip_speaker_tags
from lint_legendas import validar_legendas
from notificar_whatsapp import enviar_mensagem_whatsapp


class SpeakerTagRegressionTests(unittest.TestCase):
    def test_only_known_or_explicit_speaker_labels_are_removed(self):
        self.assertEqual(strip_speaker_tags('Cihan: Vamos.\\NAlya: Estou indo.'), 'Vamos.\\NEstou indo.')
        self.assertEqual(strip_speaker_tags('Dizendo: "Seu pai é um assassino!"'),
                         'Dizendo: "Seu pai é um assassino!"')
        self.assertEqual(strip_speaker_tags('[Policial]: Todos para fora.'), 'Todos para fora.')


class LinterRegressionTests(unittest.TestCase):
    def make_files(self, directory, translated):
        original = Path(directory) / "original.srt"
        output = Path(directory) / "traducao.srt"
        original.write_text(
            "1\n00:00:01,000 --> 00:00:02,000\nMerhaba.\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nNasılsın?\n",
            encoding="utf-8",
        )
        output.write_text(translated, encoding="utf-8")
        return original, output

    def test_exact_ids_and_timestamps_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            original, output = self.make_files(
                directory,
                "1\n00:00:01.000 --> 00:00:02.000\nOlá.\n\n"
                "2\n00:00:03,000 --> 00:00:04,000\nTudo bem?\n",
            )
            result = validar_legendas(output, original)
            self.assertTrue(result["valido"], result)

    def test_id_and_timestamp_mismatches_fail_even_when_counts_match(self):
        with tempfile.TemporaryDirectory() as directory:
            original, output = self.make_files(
                directory,
                "7\n00:00:01,000 --> 00:00:02,500\nOlá.\n\n"
                "2\n00:00:03,000 --> 00:00:04,000\nTudo bem?\n",
            )
            result = validar_legendas(output, original)
            self.assertFalse(result["valido"])
            self.assertTrue(any("ID diferente" in error for error in result["erros"]))
            self.assertTrue(any("timestamps diferentes" in error for error in result["erros"]))

    def test_malformed_blocks_fail_instead_of_being_silently_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            original, output = self.make_files(directory, "1\nlinha sem timestamp\ntexto\n")
            result = validar_legendas(output, original)
            self.assertFalse(result["valido"])
            self.assertIn("SRT PT-BR inválido", result["erros"][0])

    def test_nonsequential_ids_fail_without_original(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "traducao.srt"
            output.write_text(
                "1\n00:00:01,000 --> 00:00:02,000\nOlá.\n\n"
                "3\n00:00:03,000 --> 00:00:04,000\nTudo bem?\n",
                encoding="utf-8",
            )
            result = validar_legendas(output)
            self.assertFalse(result["valido"])
            self.assertTrue(any("não estão em sequência" in error for error in result["erros"]))

    def test_paired_srt_timestamp_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            original, output = self.make_files(
                directory,
                "1\n00:00:01,000 --> 00:00:02,000\nOlá.\n\n"
                "2\n00:00:03,000 --> 00:00:04,000\nTudo bem?\n",
            )
            paired = Path(directory) / "traducao.com_orador.srt"
            paired.write_text(
                "1\n00:00:01,000 --> 00:00:02,000\nAlya: Olá.\n\n"
                "2\n00:00:03,000 --> 00:00:04,100\nCihan: Tudo bem?\n",
                encoding="utf-8",
            )
            result = validar_legendas(output, original, arquivo_pareado=paired)
            self.assertFalse(result["valido"])
            self.assertTrue(any("timestamps diferentes entre versão limpa" in error for error in result["erros"]))

    def test_empty_paired_srt_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            _, output = self.make_files(
                directory,
                "1\n00:00:01,000 --> 00:00:02,000\nOlá.\n\n"
                "2\n00:00:03,000 --> 00:00:04,000\nTudo bem?\n",
            )
            paired = Path(directory) / "empty.com_orador.srt"
            paired.write_text("", encoding="utf-8")
            result = validar_legendas(output, arquivo_pareado=paired)
            self.assertFalse(result["valido"])
            self.assertTrue(any("Contagem SRT pareado divergente" in error for error in result["erros"]))

    def test_advisory_skill_rule_is_not_promoted_by_blocking_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            original, output = self.make_files(
                directory,
                "1\n00:00:01,000 --> 00:00:02,000\nMinha mãe.\n\n"
                "2\n00:00:03,000 --> 00:00:04,000\nTudo bem?\n",
            )
            result = validar_legendas(output, original, regras_como_erros=True)
            self.assertTrue(result["valido"], result)
            self.assertTrue(any(item["regra_id"] == "VOCATIVO_MATERNO" for item in result["inconsistencias_regras"]))

    def test_skill_rules_detect_hallucinations_as_warnings_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            original, output = self.make_files(
                directory,
                "1\n00:00:01,000 --> 00:00:02,000\nIrmão, um pássaro!\n\n"
                "2\n00:00:03,000 --> 00:00:04,000\nDr. Boran chegou.\n",
            )
            result = validar_legendas(output, original, verificar_regras_skill=True, regras_como_erros=False)
            self.assertTrue(result["valido"])
            self.assertEqual(len(result["inconsistencias_regras"]), 2)
            rule_ids = [inc["regra_id"] for inc in result["inconsistencias_regras"]]
            self.assertIn("ASR_PASSARO", rule_ids)
            self.assertIn("DESAMBIG_BURHAN_BORAN", rule_ids)

    def test_skill_rules_block_when_configured_as_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            original, output = self.make_files(
                directory,
                "1\n00:00:01,000 --> 00:00:02,000\nDr. Boran chegou.\n\n"
                "2\n00:00:03,000 --> 00:00:04,000\nTudo bem?\n",
            )
            result = validar_legendas(output, original, verificar_regras_skill=True, regras_como_erros=True)
            self.assertFalse(result["valido"])
            self.assertTrue(any("Homófono Dr. Burhan" in err for err in result["erros"]))



class MediaCliRegressionTests(unittest.TestCase):
    def test_render_uses_generator_positional_arguments_and_expected_stem(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "Episode_36.pt-BR.srt"
            output = Path(directory) / "rendered"
            source.write_text("1\n00:00:01,000 --> 00:00:02,000\nCihan: Olá.\n", encoding="utf-8")

            success = media_cli.cmd_render(SimpleNamespace(srt=str(source), out_dir=str(output)))

            self.assertTrue(success)
            expected = [
                "Episode_36.pt-BR.srt",
                "Episode_36.com_orador.pt-BR.srt",
                "Episode_36.ass",
                "Episode_36.com_orador.ass",
            ]
            self.assertEqual(sorted(path.name for path in output.iterdir()), sorted(expected))
            self.assertIn("Cihan: Olá.", (output / "Episode_36.com_orador.pt-BR.srt").read_text())
            self.assertIn("Olá.", (output / "Episode_36.pt-BR.srt").read_text())

    def test_run_skip_completes_with_expected_output_names_and_lint(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "episode.pt-BR.srt"
            output = Path(directory) / "output"
            source.write_text("1\n00:00:01,000 --> 00:00:02,000\nOlá.\n", encoding="utf-8")
            args = SimpleNamespace(
                input_srt=str(source), out_dir=str(output), engine="skip", notify=False, notify_to=None
            )

            self.assertTrue(media_cli.cmd_run(args))
            self.assertTrue((output / "episode.pt-BR.srt").is_file())
            self.assertTrue((output / "episode.com_orador.pt-BR.srt").is_file())
            self.assertTrue((output / "episode.ass").is_file())
            self.assertTrue((output / "episode.com_orador.ass").is_file())

    def test_quality_gate_failure_stops_pipeline_before_success_notification(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "episode.srt"
            output = Path(directory) / "out"
            source.write_text("1\n00:00:01,000 --> 00:00:02,000\nOlá.\n", encoding="utf-8")
            args = SimpleNamespace(
                input_srt=str(source), out_dir=str(output), engine="skip", notify=True, notify_to=None
            )
            with patch.object(media_cli, "run_command", side_effect=[True, False]) as run:
                self.assertFalse(media_cli.cmd_run(args))
            self.assertEqual(run.call_count, 2)
            self.assertIn("lint_legendas.py", run.call_args.args[0][1])


class WhatsAppNotifierRegressionTests(unittest.TestCase):
    def test_request_encodes_instance_and_redacts_recipient_in_logs(self):
        response = MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        with patch("notificar_whatsapp.urllib.request.urlopen", return_value=response) as urlopen, patch(
            "builtins.print"
        ) as print_mock:
            self.assertTrue(enviar_mensagem_whatsapp(
                "Teste", api_url="https://example.test/", api_key="key",
                instance="home assistant", destinatario="+55 (11) 99999-1234",
            ))

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.test/message/sendText/home%20assistant")
        self.assertEqual(json.loads(request.data)["number"], "5511999991234")
        self.assertIn("1234", print_mock.call_args.args[0])
        self.assertNotIn("5511999991234", print_mock.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
