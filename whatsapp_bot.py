#!/usr/bin/env python3
"""
WhatsApp Bot para Galaxy A70 (Termux).
Recebe webhooks da Evolution API (v2) e permite controle remoto da infraestrutura doméstica:
- Status do A70, Termux, memória, serviços e roteador FTP
- Pré-cache de áudio (.audio.m4a) sob demanda
- Disparo de workflows de legendagem no GitHub Actions
- Consulta da fila e status de execuções no GitHub Actions
- Listagem de arquivos e status dos episódios no FTP
- Encaminhamento transparente de webhooks para o Home Assistant
"""

import http.server
import json
import os
import re
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

PORT = int(os.environ.get("BOT_PORT", "8088"))
AUTHORIZED_NUMBERS = [
    "5511975526876",  # César
]
EVOLUTION_API_URL = os.environ.get("EVOLUTION_API_URL", "https://wa.luisices.com.br").rstrip("/")
def get_github_token() -> str:
    """Recupera o token do GitHub de variáveis de ambiente ou arquivos de configuração."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    token_file = os.path.expanduser("~/.github_token")
    if os.path.isfile(token_file):
        try:
            with open(token_file, "r", encoding="utf-8") as f:
                t = f.read().strip()
                if t:
                    return t
        except Exception:
            pass
    gh_hosts = os.path.expanduser("~/.config/gh/hosts.yml")
    if os.path.isfile(gh_hosts):
        try:
            with open(gh_hosts, "r", encoding="utf-8") as f:
                for line in f:
                    if "oauth_token:" in line:
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
    return ""


def get_evolution_key() -> str:
    """Recupera a chave da Evolution API de env var ou arquivo ~/.evolution_key."""
    key = os.environ.get("EVOLUTION_API_KEY", "").strip()
    if key:
        return key
    key_file = os.path.expanduser("~/.evolution_key")
    if os.path.isfile(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                k = f.read().strip()
                if k:
                    return k
        except Exception:
            pass
    return ""


GITHUB_TOKEN = get_github_token()
EVOLUTION_API_KEY = get_evolution_key()
EVOLUTION_INSTANCE = os.environ.get("EVOLUTION_INSTANCE", "homeassistant")
HA_WEBHOOK_URL = os.environ.get(
    "HA_WEBHOOK_URL",
    "https://ha.luisices.com.br/api/webhook/whatsapp-incoming",
)
GITHUB_REPO = os.environ.get("GITHUB_REPO", "ccesargarcia/media-pipeline")
FTP_HOST = os.environ.get("FTP_HOST", "192.168.0.1")
FTP_PORT = int(os.environ.get("FTP_PORT", "21"))
FTP_AUTH = os.environ.get("FTP_AUTH", "admin:63274c0954")
FIRETV_HOST = os.environ.get("FIRETV_HOST", "192.168.0.218")
FIRETV_PORT = int(os.environ.get("FIRETV_PORT", "5555"))


def send_whatsapp(recipient: str, text: str) -> bool:
    """Envia uma mensagem de texto pelo WhatsApp através da Evolution API."""
    num_limpo = "".join(filter(str.isdigit, recipient))
    if not num_limpo:
        return False

    url = f"{EVOLUTION_API_URL}/message/sendText/{urllib.parse.quote(EVOLUTION_INSTANCE)}"
    payload = json.dumps({"number": num_limpo, "text": text.strip()}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "apikey": EVOLUTION_API_KEY,
            "User-Agent": "A70-WhatsApp-Bot/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.status in (200, 201)
    except Exception as e:
        print(f"[Bot] Falha ao enviar resposta para WhatsApp: {e}", file=sys.stderr)
        return False


def forward_to_homeassistant(raw_body: bytes) -> None:
    """Encaminha o webhook original de forma assíncrona para o Home Assistant."""
    try:
        req = urllib.request.Request(
            HA_WEBHOOK_URL,
            data=raw_body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "A70-Forwarder/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8):
            pass
    except Exception as e:
        # Silencioso se o HA não estiver ouvindo esse endpoint
        pass


def check_port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    """Testa se uma porta TCP está respondendo."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def normalizar_temporada(temp_arg: str, ep_num: int) -> str:
    """Normaliza o nome da temporada a partir de argumentos ou número do episódio."""
    temp_arg_clean = temp_arg.strip().lower()
    if temp_arg_clean in ("1", "primeira", "temp1", "t1"):
        return "Primeira Temporada"
    elif temp_arg_clean in ("2", "segunda", "temp2", "t2"):
        return "Segunda Temporada"
    elif temp_arg_clean in ("3", "terceira", "temp3", "t3"):
        return "Terceira Temporada"

    # Inferência por número do episódio
    if ep_num >= 64:
        return "Terceira Temporada"
    elif ep_num >= 35:
        return "Segunda Temporada"
    else:
        return "Primeira Temporada"


def cmd_help() -> str:
    return (
        "🤖 *Galaxy A70 — Central de Comandos*\n\n"
        "Comandos disponíveis:\n\n"
        "📊 *status*\n"
        "→ Exibe saúde do A70, memória RAM, portas ativas e FTP.\n\n"
        "⚡ *precache <ep> [temporada]*\n"
        "→ Extrai áudio .m4a no A70 e salva no FTP (ex: `precache 55` ou `precache 64 3`).\n\n"
        "🚀 *legendar <ep> [temporada]*\n"
        "→ Dispara o pipeline de legendagem no GitHub Actions (ex: `legendar 55`).\n\n"
        "⏳ *runs* ou *fila*\n"
        "→ Mostra status e progresso dos últimos workflows no GitHub Actions.\n\n"
        "📁 *ftp [temporada]*\n"
        "→ Lista arquivos e legendas da temporada no FTP (ex: `ftp 2` ou `ftp 3`).\n\n"
        "📺 *tv <comando>*\n"
        "→ Testa conectividade com Fire TV (ex: `tv status`).\n\n"
        "💡 *Dica:* Você pode digitar apenas o número do episódio no precache e legendar!"
    )


def cmd_status() -> str:
    # Uptime
    uptime_str = "Desconhecido"
    try:
        res = subprocess.run(["uptime"], capture_output=True, text=True, timeout=3)
        uptime_str = res.stdout.strip()
    except Exception:
        pass

    # Memória
    ram_str = "N/A"
    try:
        res = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=3)
        lines = res.stdout.strip().splitlines()
        if len(lines) >= 2:
            ram_str = lines[1]
    except Exception:
        pass

    # Armazenamento
    disk_str = "N/A"
    try:
        res = subprocess.run(["df", "-h", os.path.expanduser("~")], capture_output=True, text=True, timeout=3)
        lines = res.stdout.strip().splitlines()
        if len(lines) >= 2:
            disk_str = lines[1]
    except Exception:
        pass

    # Portas
    p_ssh = "🟢 Ativa" if check_port_open("127.0.0.1", 2222) else "🔴 Inativa"
    p_socks = "🟢 Ativa" if check_port_open("127.0.0.1", 1080) else "🔴 Inativa"
    p_ftp_relay = "🟢 Ativa" if check_port_open("127.0.0.1", 2121) else "🔴 Inativa"
    p_adb_relay = "🟢 Ativa" if check_port_open("127.0.0.1", 5555) else "🔴 Inativa"
    p_bot = "🟢 Ativa (8088)"

    # Dispositivos locais
    ftp_ok = "🟢 Conectado" if check_port_open(FTP_HOST, FTP_PORT) else "🔴 Inacessível"
    tv_ok = "🟢 Conectado" if check_port_open(FIRETV_HOST, FIRETV_PORT) else "🟡 Standby/Desligada"

    return (
        "📊 *Status do Sistema — Galaxy A70*\n\n"
        f"⏱️ *Uptime:* {uptime_str}\n\n"
        f"💾 *Memória RAM:* `{ram_str}`\n\n"
        f"📂 *Armazenamento:* `{disk_str}`\n\n"
        "🔌 *Serviços Locais:*\n"
        f"• SSH (2222): {p_ssh}\n"
        f"• SOCKS5 Proxy (1080): {p_socks}\n"
        f"• FTP Relay (2121): {p_ftp_relay}\n"
        f"• Fire TV Relay (5555): {p_adb_relay}\n"
        f"• WhatsApp Bot: {p_bot}\n\n"
        "🌐 *Rede Doméstica:*\n"
        f"• Roteador FTP ({FTP_HOST}:{FTP_PORT}): {ftp_ok}\n"
        f"• Fire TV Stick ({FIRETV_HOST}:{FIRETV_PORT}): {tv_ok}"
    )


def run_precache_worker(recipient: str, stem: str, season: str) -> None:
    """Executa o script de pré-cache em segundo plano e notifica ao concluir."""
    script_path = os.path.expanduser("~/precache_audios.sh")
    t0 = time.time()
    try:
        proc = subprocess.run(
            ["bash", script_path, stem, season],
            capture_output=True,
            text=True,
            timeout=600,
        )
        elapsed = int(time.time() - t0)
        if proc.returncode == 0:
            msg = (
                f"✅ *[Pré-cache Concluído]*\n\n"
                f"🎬 Episódio: `{stem}`\n"
                f"📂 Temporada: *{season}*\n"
                f"⏱️ Tempo total: *{elapsed}s*\n\n"
                f"O arquivo `.audio.m4a` está salvo no FTP e pronto para legendagem super rápida!"
            )
        else:
            err_snip = proc.stderr.strip()[-300:] or proc.stdout.strip()[-300:]
            msg = (
                f"❌ *[Falha no Pré-cache]*\n\n"
                f"Episódio: `{stem}`\n"
                f"Erro:\n```{err_snip}```"
            )
    except subprocess.TimeoutExpired:
        msg = f"⚠️ *[Timeout no Pré-cache]*\n\nO pré-cache de `{stem}` ultrapassou o limite de 10 minutos."
    except Exception as e:
        msg = f"❌ *[Erro no Pré-cache]*: {e}"

    send_whatsapp(recipient, msg)


def cmd_precache(recipient: str, args: List[str]) -> str:
    if not args:
        return "⚠️ Uso incorreto: informe o número do episódio.\nExemplo: `precache 55` ou `precache 64 3`"

    m = re.search(r"\d+", args[0])
    if not m:
        return f"❌ Número de episódio inválido: `{args[0]}`"

    ep_num = int(m.group(0))
    stem = f"Uzak_Sehir_-_Episode_{ep_num:02d}" if ep_num < 10 else f"Uzak_Sehir_-_Episode_{ep_num}"
    season_arg = args[1] if len(args) > 1 else ""
    season = normalizar_temporada(season_arg, ep_num)

    # Inicia em thread separada
    t = threading.Thread(target=run_precache_worker, args=(recipient, stem, season), daemon=True)
    t.start()

    return (
        f"⚡ *[Pré-cache Iniciado]*\n\n"
        f"Extraindo áudio de `{stem}.mp4` ({season}) no Galaxy A70...\n"
        f"O processamento é feito localmente sem recodificar.\n\n"
        f"⏳ Avisarei aqui assim que for concluído e salvo no FTP!"
    )


def cmd_legendar(args: List[str]) -> str:
    if not args:
        return "⚠️ Uso incorreto: informe o número do episódio.\nExemplo: `legendar 55` ou `legendar 64 3`"

    m = re.search(r"\d+", args[0])
    if not m:
        return f"❌ Número de episódio inválido: `{args[0]}`"

    ep_num = int(m.group(0))
    video_filename = f"Uzak_Sehir_-_Episode_{ep_num:02d}.mp4" if ep_num < 10 else f"Uzak_Sehir_-_Episode_{ep_num}.mp4"
    season_arg = args[1] if len(args) > 1 else ""
    season = normalizar_temporada(season_arg, ep_num)

    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/legendar_ftp.yml/dispatches"
    payload = json.dumps({
        "ref": "main",
        "inputs": {
            "video_filename": video_filename,
            "season": season,
            "network_mode": "tailscale",
            "usar_precache_audio": True,
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "A70-WhatsApp-Bot/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 204:
                return (
                    f"🚀 *[Workflow Disparado com Sucesso]*\n\n"
                    f"🎬 Vídeo: `{video_filename}`\n"
                    f"📂 Temporada: *{season}*\n"
                    f"⚡ Modo de Rede: *Tailscale / WireGuard*\n"
                    f"🎵 Pré-cache de Áudio: *Ativado*\n\n"
                    f"💡 O GitHub Actions iniciará o processamento em instantes. Digite *runs* para acompanhar."
                )
            else:
                return f"⚠️ Resposta inesperada do GitHub: HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")[:300]
        return f"❌ Erro ao disparar no GitHub (HTTP {e.code}):\n```{err}```"
    except Exception as e:
        return f"❌ Falha de conexão com a API do GitHub: {e}"


def cmd_runs() -> str:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs?per_page=4"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "A70-WhatsApp-Bot/1.0",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            runs = data.get("workflow_runs", [])
            if not runs:
                return "ℹ️ Nenhuma execução recente encontrada no repositório."

            linhas = ["⏳ *Últimas Execuções no GitHub Actions:*\n"]
            for r in runs:
                status = r.get("status", "")
                conclusion = r.get("conclusion")
                name = r.get("display_title") or r.get("name", "Workflow")
                run_id = r.get("id")

                if status == "in_progress":
                    icon = "🔄 *Em andamento*"
                elif status == "queued":
                    icon = "⏳ *Na fila*"
                elif status == "completed":
                    if conclusion == "success":
                        icon = "✅ *Concluído com Sucesso*"
                    elif conclusion == "failure":
                        icon = "❌ *Falhou*"
                    elif conclusion == "cancelled":
                        icon = "⏹️ *Cancelado*"
                    else:
                        icon = f"⚪ *{conclusion}*"
                else:
                    icon = f"⚪ *{status}*"

                linhas.append(f"• *#{run_id}* — {icon}\n  `{name}`\n")

            linhas.append("💡 Para disparar nova legenda, digite: `legendar <número>`")
            return "\n".join(linhas)
    except Exception as e:
        return f"❌ Erro ao consultar execuções no GitHub: {e}"


def cmd_ftp(args: List[str]) -> str:
    season_arg = args[0] if args else "2"
    season = normalizar_temporada(season_arg, 50)
    encoded_season = urllib.parse.quote(season)
    ftp_url = f"ftp://{FTP_HOST}:{FTP_PORT}/G/Series/Longe%20demais%20-%20{encoded_season}/"

    try:
        cmd = ["curl", "-s", "--list-only", "-u", FTP_AUTH, ftp_url]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        if res.returncode != 0 or not res.stdout.strip():
            return f"❌ Não foi possível listar a pasta `{season}` no FTP."

        files = [f.strip() for f in res.stdout.splitlines() if f.strip()]
        mp4s = sorted([f for f in files if f.endswith(".mp4") and "Episode_" in f])
        audios = set([f for f in files if f.endswith(".audio.m4a")])
        srts = set([f for f in files if f.endswith(".pt-BR.srt")])

        if not mp4s:
            return f"📂 Pasta *{season}* no FTP não possui arquivos .mp4 encontrados."

        linhas = [f"📁 *Status no FTP — {season}:*\n"]
        linhas.append(f"• Total de Vídeos: *{len(mp4s)}*")
        linhas.append(f"• Áudios em Pré-cache: *{len(audios)}*")
        linhas.append(f"• Legendas Prontas: *{len(srts)}*\n")
        linhas.append("Últimos episódios disponíveis:")

        for mp4 in mp4s[-6:]:
            stem = mp4[:-4]
            tem_audio = "🎵" if f"{stem}.audio.m4a" in audios else "⚪"
            tem_srt = "📝" if f"{stem}.pt-BR.srt" in srts else "⏳"
            linhas.append(f"• `{stem}`: {tem_audio} Áudio | {tem_srt} Legenda")

        return "\n".join(linhas)
    except Exception as e:
        return f"❌ Erro ao consultar FTP: {e}"


def cmd_tv(args: List[str]) -> str:
    is_open = check_port_open(FIRETV_HOST, FIRETV_PORT, timeout=2.0)
    if not is_open:
        return (
            f"📺 *Fire TV Stick ({FIRETV_HOST}:{FIRETV_PORT})*\n\n"
            f"Status: 🟡 *Standby ou Desligada*\n"
            f"A porta ADB 5555 não respondeu. Ligue a TV para enviar comandos remotos."
        )

    subcmd = args[0].lower() if args else "status"
    if subcmd == "status":
        return f"📺 *Fire TV Stick:* 🟢 *Conectada e respondendo na porta 5555!*"
    
    # Comandos ADB se solicitado
    keymap = {
        "pause": "KEYCODE_MEDIA_PLAY_PAUSE",
        "play": "KEYCODE_MEDIA_PLAY_PAUSE",
        "home": "KEYCODE_HOME",
        "volup": "KEYCODE_VOLUME_UP",
        "voldown": "KEYCODE_VOLUME_DOWN",
        "back": "KEYCODE_BACK",
    }
    if subcmd in keymap:
        key = keymap[subcmd]
        try:
            subprocess.run(["adb", "connect", f"{FIRETV_HOST}:{FIRETV_PORT}"], capture_output=True, timeout=4)
            subprocess.run(["adb", "-s", f"{FIRETV_HOST}:{FIRETV_PORT}", "shell", "input", "keyevent", key], capture_output=True, timeout=4)
            return f"📺 Comando `{subcmd}` ({key}) enviado para o Fire TV!"
        except Exception as e:
            return f"❌ Falha ao enviar comando ADB: {e}"

    return f"📺 Comandos suportados: `tv status`, `tv play`, `tv pause`, `tv home`."


def process_incoming_text(sender_clean: str, text: str) -> Optional[str]:
    """Interpreta a mensagem recebida e retorna a resposta se for um comando válido."""
    t = text.strip()
    if not t:
        return None

    # Normaliza comandos: remove ! ou / se houver
    if t.startswith(("!", "/")):
        t = t[1:].strip()

    parts = t.split()
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in ("ajuda", "menu", "comandos", "start", "oi", "ola", "olá"):
        return cmd_help()
    elif cmd in ("status", "info"):
        return cmd_status()
    elif cmd in ("precache", "extrair", "audio"):
        return cmd_precache(sender_clean, args)
    elif cmd in ("legendar", "legenda", "transcrever"):
        return cmd_legendar(args)
    elif cmd in ("runs", "fila", "status_runs", "jobs"):
        return cmd_runs()
    elif cmd in ("ftp", "arquivos", "series"):
        return cmd_ftp(args)
    elif cmd in ("tv", "firetv"):
        return cmd_tv(args)
    elif re.match(r"^\d+$", cmd):
        # Se o usuário digitou apenas um número (ex: "55")
        return (
            f"💡 Você enviou o número *{cmd}*.\n\n"
            f"O que deseja fazer?\n"
            f"• `legendar {cmd}` — Iniciar legendagem no GitHub Actions\n"
            f"• `precache {cmd}` — Extrair áudio no A70 e salvar no FTP"
        )
    return None


class WebhookHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)

        # Responde 200 OK imediatamente para a Evolution API não dar timeout
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"received"}')

        # Encaminha para Home Assistant em segundo plano
        threading.Thread(target=forward_to_homeassistant, args=(raw_body,), daemon=True).start()

        # Processa mensagem
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception:
            return

        # Verifica evento
        event = payload.get("event")
        if event != "messages.upsert":
            return

        data = payload.get("data")
        if not data:
            return

        # Normaliza para lista se vier objeto único
        msg_items = data if isinstance(data, list) else [data]

        for item in msg_items:
            key = item.get("key", {})
            if key.get("fromMe", False):
                continue  # Ignora mensagens enviadas pelo próprio bot

            remote_jid = key.get("remoteJid", "")
            sender_num = "".join(filter(str.isdigit, remote_jid.split("@")[0]))

            # Valida remetente autorizado
            if sender_num not in AUTHORIZED_NUMBERS:
                continue

            msg_content = item.get("message", {})
            text = (
                msg_content.get("conversation")
                or msg_content.get("extendedTextMessage", {}).get("text")
                or ""
            )

            if not text:
                continue

            print(f"[Bot] Mensagem recebida de {sender_num}: {text}", flush=True)
            resposta = process_incoming_text(sender_num, text)
            if resposta:
                send_whatsapp(sender_num, resposta)

    def log_message(self, format, *args):
        # Log simplificado
        print(f"[HTTP] {self.address_string()} - {format % args}", flush=True)


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def main():
    print(f"🚀 Iniciando WhatsApp Bot no Galaxy A70 na porta {PORT}...")
    server = ThreadedHTTPServer(("0.0.0.0", PORT), WebhookHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹️ Encerrando servidor...")
        server.server_close()


if __name__ == "__main__":
    main()
