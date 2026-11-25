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


FTP_PROXY_ENV_VARS = (
    "FTP_PROXY",
    "ftp_proxy",
    "TAILSCALE_FTP_PROXY",
    "ALL_PROXY",
    "all_proxy",
)

_PACKER_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_PACKER_RE = re.compile(
    r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\('((?:\\.|[^'\\])*)',(\d+),(\d+),'((?:\\.|[^'\\])*)'\.split\('\|'\)(?:,\d+,\{\})?\)\)",
    re.S,
)
_STREAM_URL_RE = re.compile(r"""https?://[^\s"'<>\\]+?\.(?:m3u8|mp4)(?:[^\s"'<>\\]*)?""", re.I)
_AD_SKIP_TERMS = ("google", "doubleclick", "analytics", "banner", "ads")
_NON_PLAYER_FRAME_TERMS = (
    "recaptcha",
    "google.com",
    "gstatic.com",
    "facebook.com",
    "doubleclick",
    "googlesyndication",
    "cloudfront.net",
    "googletagmanager",
)


def _clean_http_env() -> list[str]:
    """Remove variáveis de proxy FTP/SOCKS do ambiente para não vazar ao Chromium/yt-dlp/ffmpeg."""
    removed: list[str] = []
    for var in FTP_PROXY_ENV_VARS:
        if var in os.environ:
            os.environ.pop(var, None)
            removed.append(var)
    return removed


def _parse_base(token: str, base: int) -> int | None:
    if base < 2 or base > len(_PACKER_ALPHABET):
        return None
    val = 0
    for ch in token:
        digit = _PACKER_ALPHABET.find(ch)
        if digit < 0 or digit >= base:
            return None
        val = val * base + digit
    return val


def _desempacotar_packer(html: str) -> list[str]:
    """Decodifica blocos Dean Edwards packer sem executar código arbitrário."""
    unpacked_blocks: list[str] = []
    for match in _PACKER_RE.finditer(html or ""):
        p_str, base_s, _count_s, k_str = match.groups()
        base = int(base_s)
        words = k_str.replace("\\'", "'").replace("\\\\", "\\").split("|")
        p_unesc = p_str.replace("\\'", "'").replace("\\\\", "\\")

        def _repl(tok: re.Match[str]) -> str:
            word = tok.group(0)
            idx = _parse_base(word, base)
            if idx is not None and 0 <= idx < len(words) and words[idx]:
                return words[idx]
            return word

        unpacked_blocks.append(re.sub(r"\b[0-9a-zA-Z]+\b", _repl, p_unesc))
    return unpacked_blocks


def _filtrar_stream_urls(urls: list[str]) -> list[str]:
    filtradas: list[str] = []
    for raw in urls:
        u = raw.strip()
        if not u:
            continue
        low = u.lower()
        if any(ext in low for ext in (".m3u8", ".mp4")) and not any(skip in low for skip in _AD_SKIP_TERMS):
            if u not in filtradas:
                filtradas.append(u)
    return filtradas


def _extrair_urls_m3u8_de_texto(texto: str) -> list[str]:
    """Extrai URLs de stream (.m3u8 prioritário) do HTML bruto ou desempacotado."""
    candidatos: list[str] = []
    for bloco in [texto or "", *_desempacotar_packer(texto or "")]:
        candidatos.extend(_STREAM_URL_RE.findall(bloco))
    filtradas = _filtrar_stream_urls(candidatos)
    m3u8 = [u for u in filtradas if ".m3u8" in u.lower()]
    return m3u8 if m3u8 else filtradas


def _eh_frame_player(frame_url: str, page_url: str = "") -> bool:
    """Identifica frames de vídeo ignorando página raiz, about:blank e widgets terceiros."""
    url = (frame_url or "").strip()
    if not url or url.startswith("about:") or (page_url and url == page_url):
        return False
    low = url.lower()
    return not any(term in low for term in _NON_PLAYER_FRAME_TERMS)


def _extrair_streams_de_frames(page, tentar_click: bool = False) -> list[str]:
    """Inspeciona iframes de player já montados procurando playlist/m3u8 direto do JWPlayer ou HTML."""
    page_url = ""
    try:
        page_url = page.url
    except Exception:
        pass

    encontrados: list[str] = []
    for frame in page.frames:
        if not _eh_frame_player(frame.url, page_url):
            continue

        try:
            jw_urls = frame.evaluate(
                """() => {
                    const out = [];
                    if (typeof jwplayer === 'function') {
                        try {
                            const inst = jwplayer();
                            const pl = inst.getPlaylist ? inst.getPlaylist() : null;
                            if (Array.isArray(pl)) {
                                for (const item of pl) {
                                    if (item && item.file) out.push(item.file);
                                    if (item && Array.isArray(item.sources)) {
                                        for (const s of item.sources) if (s && s.file) out.push(s.file);
                                    }
                                }
                            }
                            const cfg = inst.getConfig ? inst.getConfig() : null;
                            if (cfg && Array.isArray(cfg.playlist)) {
                                for (const item of cfg.playlist) {
                                    if (item && item.file) out.push(item.file);
                                    if (item && Array.isArray(item.sources)) {
                                        for (const s of item.sources) if (s && s.file) out.push(s.file);
                                    }
                                }
                            }
                        } catch (e) {}
                    }
                    return out;
                }"""
            )
            if isinstance(jw_urls, list):
                encontrados.extend(_filtrar_stream_urls([str(u) for u in jw_urls]))
        except Exception:
            pass

        if encontrados:
            return encontrados

        try:
            html = frame.content()
            encontrados.extend(_extrair_urls_m3u8_de_texto(html))
        except Exception:
            pass

        if encontrados:
            return encontrados

        if tentar_click:
            for sel in ("#vplayer", ".jw-display-icon-container", ".jw-icon-display", "video"):
                try:
                    loc = frame.locator(sel).first
                    if loc.is_visible(timeout=500):
                        loc.click(timeout=1000)
                        break
                except Exception:
                    pass
            try:
                frame.evaluate("() => { if (typeof jwplayer === 'function') { jwplayer().play(); } }")
            except Exception:
                pass

    return _filtrar_stream_urls(encontrados)


def capturar_stream_episodio(url_episodio: str) -> str:
    removed_proxies = _clean_http_env()
    if removed_proxies:
        print(f"==> [ENV] Removido proxy FTP do extrator: {', '.join(removed_proxies)}", flush=True)
    print(f"==> Acessando página: {url_episodio}", flush=True)
    video_urls: list[str] = []
    all_requests: list[str] = []
    failed_requests: list[str] = []
    error_responses: list[str] = []
    console_errors: list[str] = []
    main_status: int | None = None
    page_url_final = url_episodio
    page_title_final = ""
    frame_urls: list[str] = []

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
                "--no-proxy-server",
            ],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # Otimização: Bloqueia recursos pesados (apenas imagens e fontes), preservando media e scripts do player
        def rotear_requisicao(route):
            req = route.request
            url_low = req.url.lower()
            res_type = req.resource_type

            # Não bloqueia playlists, streams nem assets do JWPlayer
            if ".m3u8" in url_low or ".mp4" in url_low or "jwplayer" in url_low or "tokvoy" in url_low:
                route.continue_()
                return

            if res_type in ("image", "font"):
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
            all_requests.append(req_url)
            if any(ext in req_url for ext in (".m3u8", ".mp4", "/playlist.m3u8", "master.m3u8")) and not any(
                skip in req_url for skip in _AD_SKIP_TERMS
            ):
                video_urls.append(req_url)

        def registrar_falha(request):
            if len(failed_requests) < 15:
                failed_requests.append(f"{request.url} -> {request.failure}")

        def registrar_resposta(response):
            if response.status >= 400 and len(error_responses) < 10:
                error_responses.append(f"{response.status} {response.url}")

        def registrar_console(msg):
            if msg.type == "error" and len(console_errors) < 10:
                console_errors.append(msg.text)

        page.on("request", interceptar_requisicao)
        page.on("requestfailed", registrar_falha)
        page.on("response", registrar_resposta)
        page.on("console", registrar_console)

        def _verificar_e_anexar(tentar_click: bool = False) -> bool:
            if any(".m3u8" in u.lower() for u in video_urls):
                return True
            for u in _extrair_streams_de_frames(page, tentar_click=tentar_click):
                if u not in video_urls:
                    video_urls.append(u)
            return any(".m3u8" in u.lower() for u in video_urls)

        try:
            main_resp = page.goto(url_episodio, timeout=45000, wait_until="domcontentloaded")
            main_status = main_resp.status if main_resp is not None else None

            # 1. Aguarda o iframe padrão do player montar antes de clicar em abas (evita destruir #tab2)
            for idx in range(12):
                if _verificar_e_anexar(tentar_click=(idx == 4)):
                    break
                time.sleep(0.5)

            # 2. Somente se o player padrão não retornou stream, alterna abas de servidor uma por vez
            if not _verificar_e_anexar():
                tab_selectors = [
                    "a[href='#tab2']",
                    "a[href='#tab1']",
                    "a[href='#tab3']",
                    "a[href='#tab4']",
                    "a[href='#tab5']",
                    ".fake_player a.lnkplay",
                ]
                for sel in tab_selectors:
                    if _verificar_e_anexar():
                        break
                    try:
                        loc = page.locator(sel).first
                        if loc.is_visible(timeout=800):
                            loc.click(timeout=1500)
                    except Exception:
                        continue
                    for step in range(8):
                        if _verificar_e_anexar(tentar_click=(step == 3)):
                            break
                        time.sleep(0.5)

            try:
                page_url_final = page.url
                page_title_final = page.title()
                frame_urls = [f.url for f in page.frames]
            except Exception:
                pass
        finally:
            browser.close()

    if not video_urls:
        print(f"[DIAG] main_status={main_status} url={page_url_final!r} title={page_title_final!r} total_requests={len(all_requests)}", flush=True)
        print(f"[DIAG] frames({len(frame_urls)}): {frame_urls}", flush=True)
        print(f"[DIAG] failed_requests({len(failed_requests)}): {failed_requests[:15]}", flush=True)
        print(f"[DIAG] error_responses({len(error_responses)}): {error_responses[:10]}", flush=True)
        print(f"[DIAG] console_errors({len(console_errors)}): {console_errors[:10]}", flush=True)
        raise RuntimeError(f"Não foi possível interceptar o stream de vídeo em: {url_episodio}")

    # Prioriza master playlist m3u8 ou o stream de mais alta qualidade
    m3u8_streams = [u for u in video_urls if ".m3u8" in u]
    if m3u8_streams:
        escolhido = m3u8_streams[-1]
    else:
        escolhido = video_urls[-1]

    print(f"==> Stream interceptado com sucesso: {escolhido}", flush=True)
    return escolhido


def _format_bar(pct: float, width: int = 24) -> str:
    pct_clamped = max(0.0, min(100.0, pct))
    filled = int(round(width * pct_clamped / 100.0))
    return "█" * filled + "░" * (width - filled)


def _run_ytdlp_with_progress(cmd_ytdlp: list) -> int:
    is_tty = sys.stdout.isatty() and os.environ.get("GITHUB_ACTIONS") != "true"
    proc = subprocess.Popen(
        cmd_ytdlp,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        errors="replace",
    )

    last_step = -1
    last_print_time = 0.0
    re_prog = re.compile(
        r"\[download\]\s+(\d+(?:\.\d+)?)%\s+of\s+~?\s*(\S+)\s+at\s+(\S+)\s+ETA\s+(\S+)(?:\s+\(frag\s+(\d+/\d+)\))?"
    )

    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.strip()
        if not line:
            continue

        m = re_prog.search(line)
        if m:
            pct = float(m.group(1))
            total = m.group(2)
            speed = m.group(3)
            eta = m.group(4)
            frag = f" (frag {m.group(5)})" if m.group(5) else ""
            bar = _format_bar(pct)
            msg = f"  📥 [{bar}] {pct:5.1f}% | {total} | {speed} | ETA {eta}{frag}"

            if is_tty:
                sys.stdout.write(f"\r{msg}")
                sys.stdout.flush()
            else:
                step = int(pct // 5)
                now = time.monotonic()
                if step > last_step or (pct >= 100.0 and last_step < 20) or (now - last_print_time >= 20.0):
                    last_step = step
                    last_print_time = now
                    print(msg, flush=True)
            continue

        # Mantém mensagens importantes (erros, remux, destino), oculta ruído repetitivo de fragmentos
        if line.startswith("[download] Destination:") or line.startswith("[Merger]") or line.startswith("[Fixup") or line.startswith("ERROR:") or line.startswith("WARNING:"):
            if is_tty:
                sys.stdout.write("\n")
            print(f"  {line}", flush=True)

    if is_tty:
        sys.stdout.write("\n")
        sys.stdout.flush()

    return proc.wait()


def baixar_stream(stream_url: str, output_path: str, referer: str, downloader: str = "auto"):
    _clean_http_env()
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
            "--newline",
            "--concurrent-fragments", "8",
            "--add-header", f"Referer: {stream_origin}/",
            "--add-header", f"Origin: {stream_origin}",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "--remux-video", "mp4",
            "-o", output_path,
            stream_url,
        ]
        returncode = _run_ytdlp_with_progress(cmd_ytdlp)
        if returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 100 * 1024 * 1024:
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
        "-nostats",
        "-progress", "pipe:1",
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
    proc = subprocess.Popen(cmd_ffmpeg, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, errors="replace")
    last_ff_time = 0.0
    out_time = "00:00:00"
    total_bytes = 0
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.strip()
        if line.startswith("out_time="):
            out_time = line.split("=", 1)[1].split(".")[0]
        elif line.startswith("total_size="):
            try:
                total_bytes = int(line.split("=", 1)[1])
            except ValueError:
                pass
        elif line == "progress=continue" or line == "progress=end":
            now = time.monotonic()
            if line == "progress=end" or now - last_ff_time >= 15.0:
                last_ff_time = now
                mb = total_bytes / (1024 * 1024)
                print(f"  📥 [FFmpeg] Tempo: {out_time} | Baixado: {mb:.1f} MB", flush=True)
    if proc.wait() != 0:
        raise RuntimeError(f"FFmpeg falhou ao baixar o stream (código {proc.returncode})")
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
