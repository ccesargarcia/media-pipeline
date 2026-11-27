#!/usr/bin/env python3
"""
Baixa um torrent (via magnet link ou URL de arquivo .torrent) usando aria2c
e envia todos os arquivos baixados diretamente para o servidor FTP via curl.
"""
import argparse
import json
import os
import posixpath
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from ftp_transport import VALID_FTP_MODES, connect_ftp, resolve_curl_proxy
from pathlib import Path

try:
    from notificar_whatsapp import enviar_mensagem_whatsapp
except ImportError:
    def enviar_mensagem_whatsapp(texto: str, **kwargs) -> bool:  # type: ignore[misc]
        return False


def formatar_tamanho(num_bytes: int) -> str:
    """Formata bytes para exibição legível (MB ou GB)."""
    if num_bytes >= 1024 ** 3:
        return f"{num_bytes / (1024 ** 3):.2f} GB"
    return f"{num_bytes / (1024 ** 2):.1f} MB"


def notificar(texto: str, ativo: bool) -> None:
    """Envia notificação no WhatsApp apenas se habilitado."""
    if not ativo:
        return
    try:
        enviar_mensagem_whatsapp(texto)
    except Exception as exc:
        print(f"[WhatsApp] Aviso ao notificar: {exc}", file=sys.stderr)


def selecionar_release_prowlarr(
    query: str,
    prowlarr_url: str,
    api_key: str,
    quality: str = "",
    min_seeders: int = 1,
    max_size_gb: float = 0.0,
) -> dict:
    """Consulta a API do Prowlarr e retorna o dicionário do release com mais seeders."""
    if not prowlarr_url or not api_key:
        raise ValueError("PROWLARR_URL e PROWLARR_API_KEY são obrigatórios para busca por nome.")

    endpoint = f"{prowlarr_url.rstrip('/')}/api/v1/search?query={urllib.parse.quote(query)}&type=search"
    req = urllib.request.Request(
        endpoint,
        headers={
            "X-Api-Key": api_key,
            "Accept": "application/json",
            "User-Agent": "MediaPipeline-Prowlarr/1.0",
        },
    )
    limite_txt = f", max={max_size_gb:.1f} GB" if max_size_gb and max_size_gb > 0 else ""
    print(f"🔎 Buscando no Prowlarr: '{query}' (filtro='{quality or 'qualquer'}'{limite_txt})...", flush=True)
    with urllib.request.urlopen(req, timeout=30) as resp:
        resultados = json.loads(resp.read().decode("utf-8"))

    if not isinstance(resultados, list) or not resultados:
        raise ValueError(f"Nenhum resultado encontrado no Prowlarr para '{query}'.")

    validos = [
        r for r in resultados
        if (r.get("magnetUrl") or r.get("downloadUrl")) and int(r.get("seeders") or 0) >= min_seeders
    ]
    if not validos:
        raise ValueError(f"Nenhum release com >= {min_seeders} seeder(s) e link válido para '{query}'.")

    q_norm = quality.strip().lower()
    if q_norm and q_norm != "qualquer":
        termos = ["4k", "2160p"] if q_norm in ("4k", "2160p") else [q_norm]
        filtrados = [r for r in validos if any(t in (r.get("title") or "").lower() for t in termos)]
        if not filtrados:
            exemplos = ", ".join((r.get("title") or "?") for r in validos[:5])
            raise ValueError(f"Nenhum release com '{quality}' encontrado. Disponíveis: {exemplos}")
        validos = filtrados

    if max_size_gb and max_size_gb > 0:
        max_bytes = int(max_size_gb * (1024 ** 3))
        cabem = [r for r in validos if int(r.get("size") or 0) <= max_bytes]
        if not cabem:
            menores = sorted(validos, key=lambda r: int(r.get("size") or 0))[:3]
            resumo = ", ".join(
                f"{r.get('title')} ({formatar_tamanho(int(r.get('size') or 0))})" for r in menores
            )
            raise ValueError(
                f"Todos os releases encontrados ultrapassam o limite de {max_size_gb:.1f} GB. Menores: {resumo}"
            )
        validos = cabem

    validos.sort(key=lambda r: int(r.get("seeders") or 0), reverse=True)
    escolhido = validos[0]
    tamanho = formatar_tamanho(int(escolhido.get("size") or 0))
    print(
        f"🎯 Selecionado: {escolhido.get('title')} | "
        f"Seeders: {escolhido.get('seeders')} | Tamanho: {tamanho} | "
        f"Indexador: {escolhido.get('indexer') or 'N/A'}",
        flush=True,
    )
    return escolhido


def buscar_torrent_prowlarr(
    query: str,
    prowlarr_url: str,
    api_key: str,
    quality: str = "",
    min_seeders: int = 1,
    max_size_gb: float = 0.0,
) -> str:
    """Consulta a API do Prowlarr e retorna o magnetUrl ou downloadUrl com mais seeders."""
    escolhido = selecionar_release_prowlarr(
        query,
        prowlarr_url,
        api_key,
        quality=quality,
        min_seeders=min_seeders,
        max_size_gb=max_size_gb,
    )
    return escolhido.get("magnetUrl") or escolhido["downloadUrl"]


def resolver_ftp_dir(ftp_dir: str, content_type: str = "qualquer") -> str:
    """Resolve o diretório de destino no FTP, direcionando jogos para /G/Jogos quando padrão."""
    destino = ftp_dir.strip() or "/G/Downloads"
    if content_type == "jogo" and destino.rstrip("/") == "/G/Downloads":
        return "/G/Jogos"
    return destino


def verificar_espaco_disco(download_dir: Path, expected_size_bytes: int, reserve_gb: float = 1.0) -> None:
    """Garante que há espaço livre suficiente no runner antes de iniciar o download."""
    if expected_size_bytes <= 0:
        return
    download_dir.mkdir(parents=True, exist_ok=True)
    livre = shutil.disk_usage(download_dir).free
    necessario = expected_size_bytes + int(reserve_gb * (1024 ** 3))
    if livre < necessario:
        raise RuntimeError(
            f"Espaço em disco insuficiente ({formatar_tamanho(livre)} livres) para baixar "
            f"{formatar_tamanho(expected_size_bytes)} com margem de segurança."
        )


def validar_e_preparar_fonte(source: str, work_dir: Path) -> str:
    """Valida a origem do torrent e baixa o .torrent caso seja uma URL HTTP(S)."""
    fonte = source.strip()
    if not fonte:
        raise ValueError("A origem do torrent (magnet link ou URL .torrent) está vazia.")

    if fonte.startswith("magnet:"):
        if "xt=urn:" not in fonte:
            raise ValueError("Magnet link inválido: parâmetro 'xt=urn:...' não encontrado.")
        return fonte

    if fonte.startswith(("http://", "https://")):
        class _MagnetRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                if newurl.startswith("magnet:"):
                    raise _MagnetRedirect(newurl)
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        class _MagnetRedirect(Exception):
            def __init__(self, magnet_url: str):
                super().__init__(magnet_url)
                self.magnet_url = magnet_url

        torrent_path = work_dir / "input.torrent"
        req = urllib.request.Request(
            fonte,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) MediaPipeline/1.0"},
        )
        opener = urllib.request.build_opener(_MagnetRedirectHandler())
        try:
            with opener.open(req, timeout=30) as resp:
                conteudo = resp.read()
        except _MagnetRedirect as redir:
            print("🧲 URL redirecionou para magnet link.", flush=True)
            return redir.magnet_url
        except urllib.error.HTTPError as err:
            loc = err.headers.get("Location", "") if err.headers else ""
            if loc.startswith("magnet:"):
                print("🧲 URL redirecionou para magnet link.", flush=True)
                return loc
            raise

        if not conteudo or not conteudo.startswith(b"d"):
            raise ValueError("O arquivo baixado da URL não parece ser um arquivo .torrent válido.")
        torrent_path.write_bytes(conteudo)
        print(f"📥 Arquivo .torrent baixado ({len(conteudo)} bytes): {torrent_path}", flush=True)
        return str(torrent_path)

    raise ValueError("Origem não suportada. Informe um magnet link ('magnet:...') ou URL HTTP(S) de um .torrent.")


DEFAULT_BT_TRACKERS = [
    "http://tracker.opentrackr.org:1337/announce",
    "https://opentracker.i2p.rocks:443/announce",
    "http://tracker.openbittorrent.com:80/announce",
    "http://open.acgnxtracker.com:80/announce",
    "https://tracker.tamersunion.org:443/announce",
    "https://tracker.gbitt.info:443/announce",
    "https://tracker.loligirl.cn:443/announce",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://open.demonii.com:1337/announce",
]


def baixar_torrent(
    target: str,
    download_dir: Path,
    max_minutes: int = 240,
    bt_stop_timeout: int = 180,
) -> None:
    """Executa o aria2c para baixar o torrent sem fazer seed após concluir."""
    download_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "aria2c",
        f"--dir={download_dir}",
        "--seed-time=0",
        f"--bt-stop-timeout={bt_stop_timeout}",
        "--bt-max-peers=100",
        "--bt-tracker-connect-timeout=10",
        f"--bt-tracker={','.join(DEFAULT_BT_TRACKERS)}",
        "--max-connection-per-server=16",
        "--enable-dht=true",
        "--enable-peer-exchange=true",
        "--bt-enable-lpd=true",
        "--file-allocation=none",
        "--summary-interval=15",
        "--console-log-level=notice",
        "--follow-torrent=mem",
        target,
    ]

    clean_env = os.environ.copy()
    for var in ("FTP_PROXY", "ftp_proxy", "ALL_PROXY", "all_proxy"):
        clean_env.pop(var, None)

    print(f"🧲 Iniciando download do torrent (timeout={max_minutes} min)...", flush=True)
    try:
        proc = subprocess.run(cmd, env=clean_env, timeout=max_minutes * 60, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Download excedeu o tempo máximo de {max_minutes} minutos.") from exc

    if proc.returncode != 0:
        raise RuntimeError(f"aria2c finalizou com código de erro {proc.returncode}.")


def listar_arquivos_baixados(download_dir: Path) -> list[tuple[Path, Path, int]]:
    """Lista recursivamente os arquivos baixados, ignorando arquivos de controle."""
    arquivos: list[tuple[Path, Path, int]] = []
    for path in sorted(download_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name.endswith(".aria2") or path.name == "input.torrent":
            continue
        rel_path = path.relative_to(download_dir)
        arquivos.append((path, rel_path, path.stat().st_size))
    return arquivos


def construir_destino_ftp(base_dir: str, subfolder_name: str, rel_path: Path) -> tuple[str, str]:
    """Calcula o diretório remoto e o nome do arquivo no FTP para um caminho relativo."""
    partes_base = base_dir.strip().rstrip("/") or "/"
    sub = subfolder_name.strip().strip("/")
    if sub:
        partes_base = posixpath.join(partes_base, sub)

    rel_parent = rel_path.parent.as_posix()
    if rel_parent and rel_parent != ".":
        remote_dir = posixpath.join(partes_base, rel_parent)
    else:
        remote_dir = partes_base

    if not remote_dir.startswith("/"):
        remote_dir = "/" + remote_dir
    return remote_dir, rel_path.name


def arquivo_existe_no_ftp(
    host: str,
    port: int,
    user: str,
    password: str,
    remote_dir: str,
    filename: str,
    expected_size: int,
    ftp_mode: str = "auto",
    tailscale_proxy: str = "",
) -> bool:
    """Verifica via FTP se o arquivo já existe com exatamente o mesmo tamanho."""
    if not user or expected_size <= 0:
        return False
    try:
        ftp, _route = connect_ftp(
            host=host,
            port=port,
            user=user,
            password=password,
            mode=ftp_mode,
            proxy_url=tailscale_proxy,
            timeout=15,
        )
        try:
            ftp.cwd(remote_dir)
            tamanho_remoto = ftp.size(filename)
        finally:
            try:
                ftp.quit()
            except Exception:
                pass
        return tamanho_remoto is not None and tamanho_remoto == expected_size
    except Exception:
        return False


def enviar_arquivo_ftp_curl(
    local_path: Path,
    host: str,
    port: int,
    user: str,
    password: str,
    remote_dir: str,
    filename: str,
    proxy_url: str = "",
) -> float:
    """Envia um arquivo local ao FTP via curl e retorna a velocidade em MB/s."""
    encoded_dir = urllib.parse.quote(remote_dir.rstrip("/") or "/", safe="/")
    encoded_file = urllib.parse.quote(filename, safe="")
    ftp_url = f"ftp://{host}:{port}{encoded_dir}/{encoded_file}"

    cmd = [
        "curl",
        "-g",
        "-#",
        "--fail",
        "--ftp-pasv",
        "--ftp-skip-pasv-ip",
        "--ftp-create-dirs",
        "--retry", "5",
        "--retry-delay", "10",
        "--retry-all-errors",
        "--retry-connrefused",
        "-u", f"{user}:{password}",
        "-T", str(local_path),
        ftp_url,
    ]
    if proxy_url:
        cmd.extend(["--proxy", proxy_url])

    inicio = time.monotonic()
    proc = subprocess.run(cmd, check=False)
    elapsed = max(time.monotonic() - inicio, 0.001)
    if proc.returncode != 0:
        raise RuntimeError(f"curl falhou ao enviar '{filename}' (código {proc.returncode}).")

    size_mb = local_path.stat().st_size / (1024 * 1024)
    return size_mb / elapsed


def executar_pipeline(args: argparse.Namespace) -> int:
    ftp_host = os.environ.get("FTP_HOST", "192.168.0.1")
    ftp_port = int(os.environ.get("FTP_PORT", "21"))
    ftp_user = os.environ.get("FTP_USER", "")
    ftp_password = os.environ.get("FTP_PASSWORD", "")

    if not ftp_user or not ftp_password:
        print("❌ Credenciais FTP (FTP_USER / FTP_PASSWORD) não configuradas.", file=sys.stderr)
        return 1

    content_type = getattr(args, "content_type", "qualquer")
    ftp_dir = resolver_ftp_dir(args.ftp_dir, content_type)
    icone = "🎮" if content_type == "jogo" else "🧲"

    work_dir = Path(args.work_dir).resolve()
    download_dir = work_dir / "downloads"
    work_dir.mkdir(parents=True, exist_ok=True)

    inicio_total = time.monotonic()
    try:
        fonte_resolvida = args.source.strip()
        expected_size = 0
        if not fonte_resolvida:
            if not args.query.strip():
                raise ValueError("Informe --source (magnet/URL) ou --query (busca no Prowlarr).")
            release = selecionar_release_prowlarr(
                args.query.strip(),
                os.environ.get("PROWLARR_URL", ""),
                os.environ.get("PROWLARR_API_KEY", ""),
                quality=args.quality,
                min_seeders=args.min_seeders,
                max_size_gb=getattr(args, "max_size_gb", 0.0),
            )
            fonte_resolvida = release.get("magnetUrl") or release["downloadUrl"]
            expected_size = int(release.get("size") or 0)
        verificar_espaco_disco(download_dir, expected_size)
        target = validar_e_preparar_fonte(fonte_resolvida, work_dir)
        notificar(
            f"{icone} *Torrent → FTP iniciado*\n📂 Destino: `{ftp_dir}`",
            args.notify_whatsapp,
        )
        baixar_torrent(
            target,
            download_dir,
            max_minutes=args.max_minutes,
            bt_stop_timeout=args.bt_stop_timeout,
        )
    except Exception as exc:
        print(f"❌ Erro na etapa de download do torrent: {exc}", file=sys.stderr)
        notificar(
            f"❌ *Torrent → FTP falhou no download*\nMotivo: {exc}",
            args.notify_whatsapp,
        )
        return 1

    arquivos = listar_arquivos_baixados(download_dir)
    if not arquivos:
        print("❌ Nenhum arquivo foi baixado pelo torrent.", file=sys.stderr)
        notificar("❌ *Torrent → FTP*: nenhum arquivo encontrado após o download.", args.notify_whatsapp)
        return 1

    total_bytes = sum(size for _, _, size in arquivos)
    print(f"\n✅ Download concluído: {len(arquivos)} arquivo(s), total {formatar_tamanho(total_bytes)}", flush=True)
    notificar(
        f"📥 *Torrent baixado!* ({len(arquivos)} arquivo(s) · {formatar_tamanho(total_bytes)})\n"
        f"📤 Iniciando upload para `{ftp_dir}`...",
        args.notify_whatsapp,
    )

    ftp_mode = getattr(args, "ftp_mode", "auto")
    tailscale_proxy = getattr(args, "tailscale_proxy", "")
    curl_proxy = (
        resolve_curl_proxy(
            mode=ftp_mode,
            proxy_url=tailscale_proxy,
            host=ftp_host,
            port=ftp_port,
        )
        or ""
    )
    rota_inicial = f"tailscale({curl_proxy})" if curl_proxy else "direct/openvpn"
    print(f"🌐 Transporte FTP selecionado ({ftp_mode}): {rota_inicial}", flush=True)

    enviados = 0
    pulados = 0
    falhas: list[str] = []

    for local_path, rel_path, size_bytes in arquivos:
        remote_dir, filename = construir_destino_ftp(ftp_dir, args.subfolder_name, rel_path)
        print("----------------------------------------------------------", flush=True)
        print(f"📄 Arquivo: {rel_path} ({formatar_tamanho(size_bytes)}) -> {remote_dir}/{filename}", flush=True)

        if args.skip_existing and arquivo_existe_no_ftp(
            ftp_host,
            ftp_port,
            ftp_user,
            ftp_password,
            remote_dir,
            filename,
            size_bytes,
            ftp_mode=ftp_mode,
            tailscale_proxy=tailscale_proxy,
        ):
            print(f"⏩ Arquivo já existe no FTP com o mesmo tamanho. Pulando.", flush=True)
            pulados += 1
            local_path.unlink(missing_ok=True)
            continue

        try:
            try:
                speed_mbs = enviar_arquivo_ftp_curl(
                    local_path,
                    ftp_host,
                    ftp_port,
                    ftp_user,
                    ftp_password,
                    remote_dir,
                    filename,
                    proxy_url=curl_proxy,
                )
            except Exception as exc:
                if curl_proxy and ftp_mode in ("auto", "tailscale"):
                    print(
                        f"⚠️ Upload via Tailscale ({curl_proxy}) falhou ({exc}); "
                        "usando fallback direto/OpenVPN...",
                        file=sys.stderr,
                    )
                    curl_proxy = ""
                    speed_mbs = enviar_arquivo_ftp_curl(
                        local_path,
                        ftp_host,
                        ftp_port,
                        ftp_user,
                        ftp_password,
                        remote_dir,
                        filename,
                        proxy_url="",
                    )
                else:
                    raise
            print(f"✅ Enviado com sucesso (~{speed_mbs:.2f} MB/s)", flush=True)
            enviados += 1
            local_path.unlink(missing_ok=True)
        except Exception as exc:
            print(f"❌ Falha ao enviar {rel_path}: {exc}", file=sys.stderr)
            falhas.append(str(rel_path))

    shutil.rmtree(work_dir, ignore_errors=True)
    duracao_total = int(time.monotonic() - inicio_total)

    print("==========================================================", flush=True)
    print(f"🏁 RESUMO TORRENT → FTP ({duracao_total}s)", flush=True)
    print(f"✅ Enviados: {enviados} | ⏩ Pulados: {pulados} | ❌ Falhas: {len(falhas)}", flush=True)
    print("==========================================================", flush=True)

    status_icon = "✅" if not falhas else ("⚠️" if enviados > 0 or pulados > 0 else "❌")
    resumo_msg = (
        f"{status_icon} *Resumo Torrent → FTP*\n\n"
        f"📂 *Destino:* `{ftp_dir}`\n"
        f"📦 *Total:* {formatar_tamanho(total_bytes)} em {duracao_total}s\n"
        f"✅ *Enviados:* {enviados}\n"
        f"⏩ *Pulados:* {pulados}\n"
        f"❌ *Falhas:* {len(falhas)}"
    )
    if falhas:
        resumo_msg += "\n\n*Arquivos com erro:*\n- " + "\n- ".join(falhas[:10])
    notificar(resumo_msg, args.notify_whatsapp)

    return 1 if falhas else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download de torrent e upload direto ao FTP.")
    parser.add_argument(
        "--content-type",
        choices=("filme_serie", "jogo", "qualquer"),
        default="qualquer",
        help="Tipo de conteúdo (jogo direciona /G/Downloads para /G/Jogos)",
    )
    parser.add_argument("--source", default="", help="Magnet link ou URL de arquivo .torrent")
    parser.add_argument("--query", default="", help="Termo de busca via API do Prowlarr (quando --source vazio)")
    parser.add_argument("--quality", default="", help="Filtro de qualidade ou release na busca Prowlarr (ex: 1080p, FitGirl, DODI, GOG)")
    parser.add_argument("--min-seeders", type=int, default=1, help="Mínimo de seeders na busca Prowlarr")
    parser.add_argument("--max-size-gb", type=float, default=0.0, help="Tamanho máximo em GB na busca Prowlarr (0 = sem limite)")
    parser.add_argument("--ftp-dir", required=True, help="Diretório base de destino no FTP")
    parser.add_argument("--subfolder-name", default="", help="Subpasta opcional dentro do diretório FTP")
    parser.add_argument("--work-dir", default="torrent_work", help="Diretório temporário de trabalho")
    parser.add_argument("--max-minutes", type=int, default=240, help="Timeout total do download em minutos")
    parser.add_argument("--bt-stop-timeout", type=int, default=180, help="Timeout do aria2c sem peers (segundos)")
    parser.add_argument("--skip-existing", action="store_true", help="Pular arquivos já existentes no FTP")
    parser.add_argument("--notify-whatsapp", action="store_true", help="Enviar notificações via WhatsApp")
    parser.add_argument(
        "--ftp-mode",
        choices=VALID_FTP_MODES,
        default="auto",
        help="Modo de transporte FTP (auto, lan, vpn, direct, tailscale)",
    )
    parser.add_argument(
        "--tailscale-proxy",
        default="",
        help="Proxy SOCKS5 do Tailscale (ex: socks5h://100.97.222.39:1080)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(executar_pipeline(parse_args()))
