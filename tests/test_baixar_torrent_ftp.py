import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import baixar_torrent_ftp as btf


class TestBaixarTorrentFtp(unittest.TestCase):
    def test_validar_magnet_valido(self):
        magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=Teste"
        with tempfile.TemporaryDirectory() as tmp:
            res = btf.validar_e_preparar_fonte(magnet, Path(tmp))
            self.assertEqual(res, magnet)

    def test_validar_magnet_invalido(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                btf.validar_e_preparar_fonte("magnet:?dn=SemHash", Path(tmp))

    def test_validar_fonte_invalida(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                btf.validar_e_preparar_fonte("ftp://exemplo.com/arquivo.torrent", Path(tmp))

    def test_validar_url_torrent(self):
        with tempfile.TemporaryDirectory() as tmp:
            resp_mock = MagicMock()
            resp_mock.read.return_value = b"d8:announce15:http://test/ance"
            resp_mock.__enter__ = MagicMock(return_value=resp_mock)
            resp_mock.__exit__ = MagicMock(return_value=False)

            opener_mock = MagicMock()
            opener_mock.open.return_value = resp_mock
            with patch("baixar_torrent_ftp.urllib.request.build_opener", return_value=opener_mock):
                res = btf.validar_e_preparar_fonte("https://exemplo.com/filme.torrent", Path(tmp))
                self.assertTrue(res.endswith("input.torrent"))
                self.assertTrue(Path(res).exists())

    def test_validar_url_redireciona_para_magnet(self):
        import urllib.error
        from email.message import Message

        magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
        hdrs = Message()
        hdrs["Location"] = magnet
        err = urllib.error.HTTPError("https://torrent.luisices.com.br/1/download", 301, "Moved", hdrs, None)

        opener_mock = MagicMock()
        opener_mock.open.side_effect = err
        with tempfile.TemporaryDirectory() as tmp:
            with patch("baixar_torrent_ftp.urllib.request.build_opener", return_value=opener_mock):
                res = btf.validar_e_preparar_fonte("https://torrent.luisices.com.br/1/download", Path(tmp))
                self.assertEqual(res, magnet)

    def test_listar_arquivos_ignora_controle(self):
        with tempfile.TemporaryDirectory() as tmp:
            dl = Path(tmp)
            (dl / "input.torrent").write_bytes(b"d...")
            (dl / "Serie").mkdir()
            (dl / "Serie" / "Ep01.mkv").write_bytes(b"12345")
            (dl / "Serie" / "Ep01.mkv.aria2").write_bytes(b"ctrl")

            arquivos = btf.listar_arquivos_baixados(dl)
            self.assertEqual(len(arquivos), 1)
            self.assertEqual(arquivos[0][1], Path("Serie/Ep01.mkv"))
            self.assertEqual(arquivos[0][2], 5)

    def test_construir_destino_ftp(self):
        remote_dir, filename = btf.construir_destino_ftp(
            "/G/Series/", "Minha Serie", Path("Season 1/Ep 01.mkv")
        )
        self.assertEqual(remote_dir, "/G/Series/Minha Serie/Season 1")
        self.assertEqual(filename, "Ep 01.mkv")

        remote_dir2, filename2 = btf.construir_destino_ftp(
            "/G/Downloads", "", Path("Filme.mkv")
        )
        self.assertEqual(remote_dir2, "/G/Downloads")
        self.assertEqual(filename2, "Filme.mkv")

    def test_enviar_arquivo_ftp_curl_codifica_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "Ep 01 [1080p].mkv"
            arquivo.write_bytes(b"abc")

            with patch("baixar_torrent_ftp.subprocess.run") as run_mock:
                run_mock.return_value = MagicMock(returncode=0)
                btf.enviar_arquivo_ftp_curl(
                    arquivo, "192.168.0.1", 21, "user", "pass", "/G/Minha Pasta", arquivo.name
                )
                cmd = run_mock.call_args[0][0]
                self.assertIn(
                    "ftp://192.168.0.1:21/G/Minha%20Pasta/Ep%2001%20%5B1080p%5D.mkv",
                    cmd,
                )

    def test_buscar_torrent_prowlarr_seleciona_mais_seeders(self):
        payload = [
            {"title": "Filme.2026.720p.WEB", "seeders": 50, "size": 1000, "magnetUrl": "magnet:?xt=urn:btih:720"},
            {"title": "Filme.2026.1080p.WEB", "seeders": 25, "size": 2000, "magnetUrl": "magnet:?xt=urn:btih:1080a"},
            {"title": "Filme.2026.1080p.BLURAY", "seeders": 80, "size": 3000, "magnetUrl": "magnet:?xt=urn:btih:1080b"},
        ]
        resp_mock = MagicMock()
        resp_mock.read.return_value = json.dumps(payload).encode("utf-8")
        resp_mock.__enter__ = MagicMock(return_value=resp_mock)
        resp_mock.__exit__ = MagicMock(return_value=False)

        with patch("baixar_torrent_ftp.urllib.request.urlopen", return_value=resp_mock):
            res = btf.buscar_torrent_prowlarr("Filme 2026", "http://100.64.0.1:9696", "abc123", quality="1080p")
            self.assertEqual(res, "magnet:?xt=urn:btih:1080b")

    def test_buscar_torrent_prowlarr_4k_casa_2160p(self):
        payload = [
            {"title": "Filme.2026.2160p.UHD", "seeders": 12, "size": 5000, "downloadUrl": "https://idx/f.torrent"},
        ]
        resp_mock = MagicMock()
        resp_mock.read.return_value = json.dumps(payload).encode("utf-8")
        resp_mock.__enter__ = MagicMock(return_value=resp_mock)
        resp_mock.__exit__ = MagicMock(return_value=False)

        with patch("baixar_torrent_ftp.urllib.request.urlopen", return_value=resp_mock):
            res = btf.buscar_torrent_prowlarr("Filme 2026", "http://100.64.0.1:9696", "abc123", quality="4K")
            self.assertEqual(res, "https://idx/f.torrent")


if __name__ == "__main__":
    unittest.main()
