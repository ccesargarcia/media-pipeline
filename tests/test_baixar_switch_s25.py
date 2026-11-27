import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import baixar_switch_s25 as sw


class TestBaixarSwitchS25(unittest.TestCase):
    def test_sanitizar_nome_arquivo(self):
        self.assertEqual(
            sw.sanitizar_nome_arquivo("The Legend of Zelda: Skyward Sword HD"),
            "The Legend of Zelda_ Skyward Sword HD",
        )

    def test_detectar_extensao_rom_magic_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p_nsp = Path(tmp) / "a.bin"
            p_nsp.write_bytes(b"PFS0\x00\x00\x00\x00")
            self.assertEqual(sw.detectar_extensao_rom(p_nsp), ".nsp")

            p_zip = Path(tmp) / "b.bin"
            p_zip.write_bytes(b"PK\x03\x04\x14\x00")
            self.assertEqual(sw.detectar_extensao_rom(p_zip), ".zip")

            p_xci = Path(tmp) / "c.bin"
            p_xci.write_bytes(b"\x00" * 0x100 + b"HEAD" + b"\x00" * 8)
            self.assertEqual(sw.detectar_extensao_rom(p_xci), ".xci")

            p_rar = Path(tmp) / "d.NSP"
            p_rar.write_bytes(b"Rar!\x1a\x07\x01\x00")
            self.assertEqual(sw.detectar_extensao_rom(p_rar), ".rar")

            p_7z = Path(tmp) / "e.NSP"
            p_7z.write_bytes(b"7z\xbc\xaf'\x1c\x00\x04")
            self.assertEqual(sw.detectar_extensao_rom(p_7z), ".7z")

    def test_listar_versoes_jogo_e_filtrar(self):
        sample_html = """
        <a href="https://app.switchsrom.com/download/zelda/0/" class="rom-dl-btn">
          <span class="rom-dl-btn__label">Base Version</span>
          <span class="rom-dl-btn__size">7.6 GB</span>
        </a>
        <a href="https://app.switchsrom.com/download/zelda/1/" class="rom-dl-btn">
          <span class="rom-dl-btn__label">Update v1.0.1</span>
          <span class="rom-dl-btn__size">450 MB</span>
        </a>
        """
        with patch("baixar_switch_s25._http_get_text", return_value=sample_html):
            versoes = sw.listar_versoes_jogo("https://app.switchsrom.com/zelda/")
            self.assertEqual(len(versoes), 2)
            self.assertEqual(sw.filtrar_versoes(versoes, "base")[0]["label"], "Base Version")
            self.assertEqual(len(sw.filtrar_versoes(versoes, "all")), 2)

    def test_resolver_link_datadock_rejeita_placeholder(self):
        html_ok = '<a href="https://datadock-host.site/f/QOU2rBoI" id="rdl-btn">Download</a>'
        with patch("baixar_switch_s25._http_get_text", return_value=html_ok):
            self.assertEqual(
                sw.resolver_link_datadock("https://app.switchsrom.com/download/zelda/0/"),
                "https://datadock-host.site/f/QOU2rBoI",
            )

        html_placeholder = '<a href="https://app.switchsrom.com/roms/" id="rdl-btn">Download</a>'
        with patch("baixar_switch_s25._http_get_text", return_value=html_placeholder):
            with self.assertRaises(RuntimeError):
                sw.resolver_link_datadock("https://app.switchsrom.com/download/zelda/0/")

    def test_obter_info_e_url_datadock(self):
        meta = json.dumps({"filename": "Zelda: Skyward Sword", "file_size": 7595066462})
        token_resp = MagicMock()
        token_resp.read.return_value = json.dumps({"token": "tok123"}).encode("utf-8")
        token_resp.__enter__ = MagicMock(return_value=token_resp)
        token_resp.__exit__ = MagicMock(return_value=False)

        with patch("baixar_switch_s25._http_get_text", return_value=meta):
            with patch("baixar_switch_s25.urllib.request.urlopen", return_value=token_resp):
                nome, size, url = sw.obter_info_e_url_datadock("https://datadock-host.site/f/QOU2rBoI")
                self.assertEqual(nome, "Zelda_ Skyward Sword")
                self.assertEqual(size, 7595066462)
                self.assertEqual(url, "https://datadock-host.site/api/f/QOU2rBoI/download?token=tok123")

    def test_validar_integridade_nsp_detecta_truncado(self):
        with tempfile.TemporaryDirectory() as tmp:
            p_ok = Path(tmp) / "ok.nsp"
            hdr = struct.pack("<4sIII", b"PFS0", 1, 4, 0) + struct.pack("<QQII", 0, 8, 0, 0) + b"a.n\x00"
            p_ok.write_bytes(hdr + b"12345678")
            sw.validar_integridade_nsp(p_ok)

            p_bad = Path(tmp) / "bad.nsp"
            p_bad.write_bytes(hdr + b"1234")
            with self.assertRaises(RuntimeError):
                sw.validar_integridade_nsp(p_bad)


if __name__ == "__main__":
    unittest.main()
