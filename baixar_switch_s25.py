#!/usr/bin/env python3
"""
Pipeline para buscar e baixar ROMs de Nintendo Switch (NSP/XCI) de app.switchsrom.com
(via DataDock) diretamente para /sdcard/NSG no Galaxy S25.
"""
import argparse
import html as html_lib
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

try:
    from notificar_whatsapp import enviar_mensagem_whatsapp
except ImportError:
    def enviar_mensagem_whatsapp(texto: str, **kwargs) -> bool:  # type: ignore[misc]
        return False

BASE_SITE = "https://app.switchsrom.com"
DATADOCK_HOST = "https://datadock-host.site"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
VALID_ROM_EXTS = (".nsp", ".xci", ".nsz", ".xcz")


def formatar_tamanho(num_bytes: int) -> str:
    """Formata bytes para exibição legível (MB ou GB)."""
    if num_bytes >= 1024 ** 3:
        return f"{num_bytes / (1024 ** 3):.2f} GB"
    return f"{num_bytes / (1024 ** 2):.1f} MB"


def sanitizar_nome_arquivo(nome: str) -> str:
    """Remove caracteres inválidos para sistema de arquivos Android (/sdcard)."""
    limpo = html_lib.unescape(nome).strip()
    limpo = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", limpo)
    limpo = re.sub(r"\s+", " ", limpo).strip(" .")
    return limpo or "switch_game"


def detectar_extensao_rom(file_path: Path) -> str:
    """Detecta a extensão real da ROM pelos magic bytes (ZIP, NSP/PFS0 ou XCI)."""
    with file_path.open("rb") as fh:
        cabecalho = fh.read(0x110)
    if cabecalho.startswith(b"PK\x03\x04"):
        return ".zip"
    if cabecalho.startswith(b"PFS0"):
        return ".nsp"
    if len(cabecalho) >= 0x104 and cabecalho[0x100:0x104] == b"HEAD":
        return ".xci"
    return ".nsp"


def _http_get_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def buscar_jogos_switchsrom(query: str, limit: int = 10) -> list[dict]:
    """Busca jogos no WordPress REST API de app.switchsrom.com."""
    url = f"{BASE_SITE}/wp-json/wp/v2/posts?search={urllib.parse.quote(query)}&per_page={limit}"
    posts = json.loads(_http_get_text(url))
    return [
        {
            "title": html_lib.unescape(p["title"]["rendered"]).strip(),
            "url": p["link"],
        }
        for p in posts
    ]


def listar_versoes_jogo(game_url: str) -> list[dict]:
    """Extrai os botões de download (Base Version, Update, DLC) da página do jogo."""
    page_html = _http_get_text(game_url)
    pattern = re.compile(
        r'<a[^>]+href=["\']([^"\']+/download/[^"\']+)["\'][^>]*class=["\'][^"\']*rom-dl-btn[^"\']*["\'][^>]*>(.*?)</a>',
        re.S | re.I,
    )
    versoes = []
    for href, inner in pattern.findall(page_html):
        label_m = re.search(r'class=["\']rom-dl-btn__label["\'][^>]*>(.*?)</span>', inner, re.S)
        size_m = re.search(r'class=["\']rom-dl-btn__size["\'][^>]*>(.*?)</span>', inner, re.S)
        label = re.sub(r"<[^>]+>", "", label_m.group(1)).strip() if label_m else "Download"
        size_txt = re.sub(r"<[^>]+>", "", size_m.group(1)).strip() if size_m else ""
        versoes.append({"label": label, "size_text": size_txt, "download_page_url": href})
    return versoes


def resolver_link_datadock(download_page_url: str) -> str:
    """Extrai o link final (#rdl-btn) da página intermediária /download/<slug>/<idx>/."""
    page_html = _http_get_text(download_page_url)
    m = re.search(
        r'(?:href=["\']([^"\']+)["\'][^>]*id=["\']rdl-btn["\']|id=["\']rdl-btn["\'][^>]*href=["\']([^"\']+)["\'])',
        page_html,
        re.I,
    )
    if not m:
        raise RuntimeError(f"Botão #rdl-btn não encontrado em {download_page_url}")
    destino = (m.group(1) or m.group(2)).strip()
    if destino.rstrip("/") in (BASE_SITE, f"{BASE_SITE}/roms"):
        raise RuntimeError(f"Jogo sem link disponível no momento (placeholder '{destino}').")
    return destino


def obter_info_e_url_datadock(share_url: str) -> tuple[str, int, str]:
    """Consulta metadados e gera token de download direto no DataDock."""
    parsed = urllib.parse.urlparse(share_url)
    share_id = parsed.path.rstrip("/").split("/")[-1]
    if not share_id:
        raise ValueError(f"Share ID inválido na URL DataDock: {share_url}")

    meta = json.loads(_http_get_text(f"{DATADOCK_HOST}/api/f/{share_id}"))
    token_req = urllib.request.Request(
        f"{DATADOCK_HOST}/api/f/{share_id}/token",
        data=b"",
        headers={"User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(token_req, timeout=20) as resp:
        token_data = json.loads(resp.read().decode("utf-8"))

    token = token_data.get("token")
    if not token:
        raise RuntimeError(f"Token não retornado pelo DataDock para {share_id}.")

    filename = sanitizar_nome_arquivo(meta.get("filename") or share_id)
    file_size = int(meta.get("file_size") or 0)
    direct_url = f"{DATADOCK_HOST}/api/f/{share_id}/download?token={urllib.parse.quote(token)}"
    return filename, file_size, direct_url


def verificar_espaco_destino(dest_dir: Path, expected_size: int, reserve_gb: float = 1.0) -> None:
    """Garante que /sdcard/NSG possui espaço livre suficiente antes do download."""
    if expected_size <= 0:
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    livre = shutil.disk_usage(dest_dir).free
    necessario = expected_size + int(reserve_gb * (1024 ** 3))
    if livre < necessario:
        raise RuntimeError(
            f"Espaço insuficiente em {dest_dir} ({formatar_tamanho(livre)} livres) "
            f"para baixar {formatar_tamanho(expected_size)}."
        )


def arquivo_ja_existe(dest_dir: Path, base_name: str, expected_size: int) -> Path | None:
    """Verifica se o arquivo já existe em dest_dir (com ou sem extensão) com tamanho compatível."""
    candidatos = [dest_dir / base_name] + [dest_dir / f"{base_name}{ext}" for ext in (*VALID_ROM_EXTS, ".zip")]
    for cand in candidatos:
        if cand.is_file() and expected_size > 0 and abs(cand.stat().st_size - expected_size) <= 1024 * 1024:
            return cand
    return None


def extrair_zip_roms(zip_path: Path, dest_dir: Path) -> list[Path]:
    """Extrai arquivos .nsp/.xci/.nsz/.xcz de um .zip para dest_dir e remove o .zip."""
    extraidos: list[Path] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            nome = Path(member.filename).name
            if Path(nome).suffix.lower() in VALID_ROM_EXTS:
                alvo = dest_dir / sanitizar_nome_arquivo(nome)
                with zf.open(member) as src, alvo.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                extraidos.append(alvo)
    if extraidos:
        zip_path.unlink(missing_ok=True)
    return extraidos


def baixar_arquivo_com_curl(
    direct_url: str,
    dest_dir: Path,
    base_name: str,
    expected_size: int = 0,
    extract_zip: bool = True,
) -> list[Path]:
    """Baixa o arquivo diretamente para dest_dir usando curl com retomada (-C -)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    verificar_espaco_destino(dest_dir, expected_size)

    existente = arquivo_ja_existe(dest_dir, base_name, expected_size)
    if existente:
        print(f"⏩ Arquivo já existe em {existente}. Pulando download.", flush=True)
        return [existente]

    part_path = dest_dir / f"{base_name}.part"
    cmd = [
        "curl",
        "-L",
        "-#",
        "--fail",
        "-C", "-",
        "--retry", "5",
        "--retry-delay", "5",
        "-A", USER_AGENT,
        "-o", str(part_path),
        direct_url,
    ]
    print(f"📥 Baixando '{base_name}' ({formatar_tamanho(expected_size)}) para {dest_dir}...", flush=True)
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"curl falhou ao baixar '{base_name}' (código {proc.returncode}).")

    ext = Path(base_name).suffix.lower()
    if ext not in (*VALID_ROM_EXTS, ".zip", ".rar", ".7z"):
        ext = detectar_extensao_rom(part_path)
        final_name = f"{base_name}{ext}"
    else:
        final_name = base_name

    final_path = dest_dir / final_name
    part_path.replace(final_path)
    print(f"✅ Salvo em: {final_path}", flush=True)

    if ext == ".zip" and extract_zip:
        print(f"📦 Extraindo ROM de {final_path.name}...", flush=True)
        extraidos = extrair_zip_roms(final_path, dest_dir)
        if extraidos:
            return extraidos
    return [final_path]


def filtrar_versoes(versoes: list[dict], version_filter: str) -> list[dict]:
    """Filtra versões desejadas (base, update, dlc ou all)."""
    vf = version_filter.strip().lower()
    if vf in ("all", "todas", "todos"):
        return versoes
    selecionadas = [v for v in versoes if vf in v["label"].lower()]
    if not selecionadas and vf == "base":
        return versoes[:1]
    return selecionadas


def executar(args: argparse.Namespace) -> int:
    dest_dir = Path(args.dest)
    game_url = args.url.strip()

    if not game_url:
        if not args.search.strip():
            print("❌ Informe --search 'Nome do Jogo' ou --url 'https://app.switchsrom.com/...'", file=sys.stderr)
            return 1
        jogos = buscar_jogos_switchsrom(args.search.strip())
        if not jogos:
            print(f"❌ Nenhum jogo encontrado em app.switchsrom.com para '{args.search}'.", file=sys.stderr)
            return 1
        print(f"🔎 Encontrados {len(jogos)} jogo(s):", flush=True)
        for idx, j in enumerate(jogos, 1):
            print(f"  {idx}. {j['title']} ({j['url']})", flush=True)
        if args.list and not args.url:
            # Lista também as versões do primeiro resultado para facilitar escolha
            game_url = jogos[0]["url"]
        else:
            game_url = jogos[0]["url"]

    versoes = listar_versoes_jogo(game_url)
    if not versoes:
        print(f"❌ Nenhum botão de download encontrado em {game_url}", file=sys.stderr)
        return 1

    print(f"\n🎮 Versões disponíveis em {game_url}:", flush=True)
    for v in versoes:
        print(f"  - {v['label']} ({v['size_text'] or 'N/A'}): {v['download_page_url']}", flush=True)

    if args.list:
        return 0

    alvo_versoes = filtrar_versoes(versoes, args.version_filter)
    if not alvo_versoes:
        print(f"❌ Nenhuma versão compatível com --version-filter '{args.version_filter}'.", file=sys.stderr)
        return 1

    arquivos_finais: list[Path] = []
    for v in alvo_versoes:
        try:
            share_url = resolver_link_datadock(v["download_page_url"])
            if not share_url.startswith(DATADOCK_HOST):
                raise RuntimeError(f"Host não suportado automaticamente: {share_url}")
            nome, tamanho, direct_url = obter_info_e_url_datadock(share_url)
            baixados = baixar_arquivo_com_curl(
                direct_url,
                dest_dir,
                nome,
                expected_size=tamanho,
                extract_zip=not args.no_extract,
            )
            arquivos_finais.extend(baixados)
        except Exception as exc:
            print(f"❌ Falha em '{v['label']}': {exc}", file=sys.stderr)
            if args.notify_whatsapp:
                enviar_mensagem_whatsapp(f"❌ *Switch → S25 falhou* ({v['label']}): {exc}")
            return 1

    if args.notify_whatsapp:
        nomes = ", ".join(p.name for p in arquivos_finais)
        enviar_mensagem_whatsapp(f"🎮 *Switch → S25 concluído!*\n📂 `{dest_dir}`\n📄 {nomes}")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Baixa ROMs Nintendo Switch de app.switchsrom.com para /sdcard/NSG.")
    parser.add_argument("--search", default="", help="Nome do jogo para buscar em app.switchsrom.com")
    parser.add_argument("--url", default="", help="URL direta da página do jogo em app.switchsrom.com")
    parser.add_argument("--dest", default="/sdcard/NSG", help="Pasta de destino no S25 (padrão: /sdcard/NSG)")
    parser.add_argument("--version-filter", default="base", help="Versão a baixar: base, update, dlc ou all")
    parser.add_argument("--list", action="store_true", help="Apenas lista jogos e versões disponíveis sem baixar")
    parser.add_argument("--no-extract", action="store_true", help="Não extrair arquivos .zip automaticamente")
    parser.add_argument("--notify-whatsapp", action="store_true", help="Notificar no WhatsApp ao concluir/falhar")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(executar(parse_args()))
