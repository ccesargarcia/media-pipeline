import sys
import types
import unittest

# Permite importar extrair_turkish123 nos testes unitários sem exigir Playwright instalado no runner de teste.
if "playwright" not in sys.modules:
    pw_mod = types.ModuleType("playwright")
    pw_sync = types.ModuleType("playwright.sync_api")
    pw_sync.sync_playwright = lambda: None  # type: ignore[attr-defined]
    sys.modules["playwright"] = pw_mod
    sys.modules["playwright.sync_api"] = pw_sync

import extrair_turkish123


class ExtrairTurkish123Tests(unittest.TestCase):
    def test_desempacotar_packer_e_extrair_m3u8(self) -> None:
        packed_html = (
            "<script type='text/javascript'>"
            "eval(function(p,a,c,k,e,d){while(c--)if(k[c])p=p.replace(new RegExp('\\\\b'+c.toString(a)+'\\\\b','g'),k[c]);return p}"
            "('6(\"7\").8({9:[{a:\"3://0.1/4/5/c/b,n,h,x,.d/e.f?t=g&s=2\"}]});',"
            "20,17,'5775765775|com|1795583226|https|hls2|03|jwplayer|vplayer|setup|sources|file|tatiatjlifgt_|00015|urlset|master|m3u8|abc'.split('|')))"
            "</script>"
        )
        unpacked = extrair_turkish123._desempacotar_packer(packed_html)
        self.assertEqual(len(unpacked), 1)
        self.assertIn("jwplayer(\"vplayer\").setup", unpacked[0])

        urls = extrair_turkish123._extrair_urls_m3u8_de_texto(packed_html)
        self.assertEqual(
            urls,
            ["https://5775765775.com/hls2/03/00015/tatiatjlifgt_,n,h,x,.urlset/master.m3u8?t=abc&s=1795583226"],
        )

    def test_eh_frame_player_filtra_widgets(self) -> None:
        page_url = "https://turkish123.pro/uzak-sehir-episode-73/"
        self.assertTrue(extrair_turkish123._eh_frame_player("https://engifuosi.com/f/tatiatjlifgt.html", page_url))
        self.assertFalse(extrair_turkish123._eh_frame_player(page_url, page_url))
        self.assertFalse(extrair_turkish123._eh_frame_player("about:blank", page_url))
        self.assertFalse(
            extrair_turkish123._eh_frame_player("https://www.google.com/recaptcha/api2/anchor?ar=1", page_url)
        )


if __name__ == "__main__":
    unittest.main()
