#!/usr/bin/env python3
"""
Extrator de stream de vídeo de turkish123.pro usando Playwright (Chromium headless).
Intercepta tráfego de rede (.m3u8 / .mp4 / stream) e baixa diretamente via yt-dlp ou ffmpeg.
Otimizado com bloqueio de anúncios/imagens e download multi-thread de fragmentos.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Erro: Playwright não instalado. Rode: pip install playwright && playwright install chromium", file=sys.stderr)
    sys.exit(1)


def capturar_stream_episodio(url_episodio: str) -> str:
    print(f"==> Acessando página: {url_episodio}", flush=True)
    video_urls = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--no-zygote",
                "--disable-gpu",
            ],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # Otimização: Bloqueia recursos desnecessários (imagens, fontes, anúncios) para carregamento quase instantâneo
        def rotear_requisicao(route):
            req = route.request
            url_low = req.url.lower()
            res_type = req.resource_type

            # Não bloqueia playlists nem streams
            if ".m3u8" in url_low or ".mp4" in url_low:
                route.continue_()
                return

            # Bloqueia tipos pesados irrelevantes para captura
            if res_type in ("image", "font", "media"):
                route.abort()
                return

            # Bloqueia redes de rastreamento e publicidade conhecidas
            ad_domains = (
                "google-analytics",
                "doubleclick",
                "googlesyndication",
                "adnxs",
                "popads",
                "adcash",
                "propellerads",
                "exoclick",
                "trafficjunky",
                "histats",
            )
            if any(ad in url_low for ad in ad_domains):
                route.abort()
                return

            route.continue_()

        page.route("**/*", rotear_requisicao)

        def interceptar_requisicao(request):
            req_url = request.url
            if any(ext in req_url for ext in (".m3u8", ".mp4", "/playlist.m3u8", "master.m3u8")) and not any(
                skip in req_url for skip in ("google", "doubleclick", "analytics", "banner", "ads")
            ):
                video_urls.append(req_url)

        page.on("request", interceptar_requisicao)

        try:
            page.goto(url_episodio, timeout=45000, wait_until="domcontentloaded")

            # Clica no player ou nos seletores de servidor
            selectors_to_click = [
                "#content-embed",
                ".fake_player a.lnkplay",
                ".playads",
                "a[href='#tab1']",
                "a[href='#tab2']",
                "iframe",
            ]
            for sel in selectors_to_click:
                if video_urls and any(".m3u8" in u for u in video_urls):
                    break
                try:
                    loc = page.locator(sel).first
                    if loc.is_visible(timeout=1000):
                        loc.click(timeout=1500)
                except Exception:
                    pass

            # Monitora requisições e encerra assim que a stream for interceptada
            for _ in range(15):
                if video_urls and any(".m3u8" in u for u in video_urls):
                    break
                time.sleep(1)

        finally:
            browser.close()

    if not video_urls:
        raise RuntimeError(f"Não foi possível interceptar o stream de vídeo em: {url_episodio}")

    # Prioriza master playlist m3u8 ou o stream de mais alta qualidade
    m3u8_streams = [u for u in video_urls if ".m3u8" in u]
    if m3u8_streams:
        escolhido = m3u8_streams[-1]
    else:
        escolhido = video_urls[-1]

    print(f"==> Stream interceptado com sucesso: {escolhido}", flush=True)
    return escolhido


def baixar_stream(stream_url: str, output_path: str, referer: str, downloader: str = "auto"):
    import urllib.parse
    parsed = urllib.parse.urlparse(stream_url)
    stream_origin = f"{parsed.scheme}://{parsed.netloc}"

    has_ytdlp = shutil.which("yt-dlp") is not None
    use_ytdlp = (downloader == "yt-dlp") or (downloader == "auto" and has_ytdlp)

    # 1. Tentativa de alta velocidade via yt-dlp (8 fragmentos simultâneos)
    if use_ytdlp:
        print(f"==> [Acelerador] Iniciando download multi-thread com yt-dlp: {output_path}", flush=True)
        cmd_ytdlp = [
            "yt-dlp",
            "--no-check-certificates",
            "--concurrent-fragments", "8",
            "--add-header", f"Referer: {stream_origin}/",
            "--add-header", f"Origin: {stream_origin}",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "--remux-video", "mp4",
            "-o", output_path,
            stream_url,
        ]
        res = subprocess.run(cmd_ytdlp)
        if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 100 * 1024 * 1024:
            print(f"==> Download concluído com sucesso via yt-dlp: {output_path} ({os.path.getsize(output_path)} bytes)", flush=True)
            return
        print("==> Aviso: yt-dlp não concluiu ou arquivo incompleto. Alternando para FFmpeg como fallback...", flush=True)

    # 2. Fallback robusto via FFmpeg com reconexão automática
    print(f"==> Iniciando download com FFmpeg em: {output_path}", flush=True)
    header_str = (
        f"Referer: {stream_origin}/\r\n"
        f"Origin: {stream_origin}\r\n"
        "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36\r\n"
    )
    cmd_ffmpeg = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-stats",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-headers",
        header_str,
        "-i",
        stream_url,
        "-c",
        "copy",
        "-bsf:a",
        "aac_adtstoasc",
        "-y",
        output_path,
    ]
    res = subprocess.run(cmd_ffmpeg)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou ao baixar o stream (código {res.returncode})")
    print(f"==> Download concluído com sucesso via FFmpeg: {output_path} ({os.path.getsize(output_path)} bytes)", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Baixa episódio de Uzak Şehir de turkish123.pro")
    parser.add_argument("episode", type=int, help="Número do episódio (ex: 33)")
    parser.add_argument("-o", "--output", help="Caminho do arquivo mp4 de saída")
    parser.add_argument("--downloader", choices=["auto", "yt-dlp", "ffmpeg"], default="auto", help="Mecanismo de download")
    args = parser.parse_args()

    ep_num = args.episode
    page_url = f"https://turkish123.pro/uzak-sehir-episode-{ep_num}/"
    output_file = args.output or f"Uzak_Sehir_-_Episode_{ep_num:02d}.mp4"

    stream_url = capturar_stream_episodio(page_url)
    baixar_stream(stream_url, output_file, page_url, downloader=args.downloader)


if __name__ == "__main__":
    main()
