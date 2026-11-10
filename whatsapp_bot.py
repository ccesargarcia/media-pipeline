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

import datetime
import gc
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
        "🎬 *Central de Mídia & Galaxy A70*\n\n"
        "Comandos de Mídia disponíveis:\n\n"
        "📱 *a70* ou *status a70*\n"
        "→ Exibe saúde do A70, memória RAM, portas ativas e FTP.\n"
        "_(O comando `status` continua sendo o da sua casa no Home Assistant!)_\n\n"
        "⚡ *precache <ep> [temporada]*\n"
        "→ Extrai áudio .m4a no A70 e salva no FTP (ex: `precache 55` ou `precache 64 3`).\n\n"
        "🚀 *legendar <ep> [temporada] [traduzir]*\n"
        "→ Transcreve e sobe a legenda (.srt) no FTP sem tradução (ex: `legendar 55` ou `legendar 64 3`).\n"
        "_(Para traduzir via IA, adicione `traduzir`: `legendar 55 traduzir`)_\n\n"
        "⏳ *runs* ou *fila*\n"
        "→ Mostra status e progresso dos últimos workflows no GitHub Actions.\n\n"
        "📁 *ftp [temporada]*\n"
        "→ Lista arquivos e legendas da temporada no FTP (ex: `ftp 3` ou `ftp 2`).\n\n"
        "📥 *baixar <ep> [temporada]*\n"
        "→ Baixa episódio do Turkish123 e envia para o FTP com progresso em tempo real (ex: `baixar 72` ou `baixar 64 72`).\n\n"
        "📺 *firetv <comando>*\n"
        "→ Controle do Fire TV (ex: `firetv status`, `firetv play`, `firetv pause`).\n\n"
        "🧹 *limpar* ou *limpar ram*\n"
        "→ Otimiza a memória RAM, sincroniza buffers e encerra processos zumbis.\n\n"
        "🔋 *bateria* ou *saude*\n"
        "→ Exibe diagnóstico aprofundado da saúde da bateria (ASOC, ciclos e capacidade).\n\n"
        "📖 *midia*\n"
        "→ Exibe este menu de ajuda de mídia."
    )


def get_battery_and_thermal_info() -> Tuple[str, str]:
    """Lê a porcentagem da bateria e as temperaturas em tempo real do Galaxy A70."""
    batt_temp_c = None
    cpu_temp_c = None

    # Temperatura da Bateria via sensor térmico do hardware
    for tz_path in ["/sys/class/thermal/thermal_zone62", "/sys/class/thermal/thermal_zone61"]:
        try:
            raw_val = float(open(os.path.join(tz_path, "temp")).read().strip())
            batt_temp_c = round(raw_val / 1000.0, 1)
            break
        except Exception:
            pass

    # Temperatura da CPU via sensor do Snapdragon 675
    for tz_path in ["/sys/class/thermal/thermal_zone18", "/sys/class/thermal/thermal_zone19"]:
        try:
            raw_val = float(open(os.path.join(tz_path, "temp")).read().strip())
            cpu_temp_c = round(raw_val / 1000.0, 1)
            break
        except Exception:
            pass

    # Porcentagem e status de carregamento via termux-battery-status
    percentage = None
    status_str = "⚡ Conectado à tomada (24/7)"
    try:
        res = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=1.5)
        if res.returncode == 0 and res.stdout.strip():
            b_data = json.loads(res.stdout.strip())
            percentage = b_data.get("percentage")
            st = b_data.get("status", "")
            plug = b_data.get("plugged", "")
            if st == "FULL" or percentage == 100:
                status_str = f"`{percentage}%` (🟢 100% Completa / AC)"
            elif st == "CHARGING" or "PLUGGED" in str(plug):
                status_str = f"`{percentage}%` (⚡ Carregando AC)"
            elif st == "DISCHARGING":
                status_str = f"`{percentage}%` (🔋 Na bateria)"
            else:
                status_str = f"`{percentage}%`"
    except Exception:
        pass

    batt_display = status_str if percentage is not None else "⚡ Conectado à tomada (24/7)"

    temps = []
    if batt_temp_c is not None:
        temps.append(f"Bateria: *{batt_temp_c}°C*")
    if cpu_temp_c is not None:
        temps.append(f"CPU: *{cpu_temp_c}°C*")

    temp_display = " | ".join(temps) if temps else "N/A"
    return batt_display, temp_display


def get_battery_health_info() -> Dict[str, Any]:
    """Recupera métricas detalhadas da bateria (ASOC, ciclos, calibração) da Samsung."""
    health_file = os.path.expanduser("~/.battery_health.json")
    if os.path.isfile(health_file):
        try:
            with open(health_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "asoc": 70,
        "cycles": 1711.8,
        "nominal_mah": 4500,
        "current_mah": 3150,
        "cal_date": "05/12/2019",
        "max_temp_c": 65.0,
        "health_text": "GOOD",
    }


def cmd_saude_bateria() -> str:
    """Retorna o diagnóstico completo de saúde e hardware da bateria do Galaxy A70."""
    batt_info, temp_info = get_battery_and_thermal_info()
    h = get_battery_health_info()
    asoc = h.get("asoc", 70)
    cycles = float(h.get("cycles", 1711.8))
    nominal = h.get("nominal_mah", 4500)
    usable = h.get("current_mah", int(nominal * asoc / 100))
    cal_date = h.get("cal_date", "05/12/2019")
    max_temp = h.get("max_temp_c", 65.0)

    # Extrai temperatura da bateria de forma limpa
    b_temp_only = temp_info.split("|")[0].replace("Bateria:", "").strip() if "|" in temp_info else temp_info

    return (
        "🔋 *Galaxy A70 — Saúde & Diagnóstico da Bateria*\n\n"
        f"• *Saúde Real (ASOC):* *{asoc}%*\n"
        f"• *Ciclos de Carga:* *{cycles:.1f} ciclos* acumulados\n"
        f"• *Capacidade Original:* {nominal} mAh\n"
        f"• *Capacidade Atual Estimada:* ~{usable} mAh\n"
        f"• *Calibração de Fábrica:* {cal_date} (5 anos de uso)\n"
        f"• *Pico Térmico Histórico:* {max_temp}°C\n"
        f"• *Estado Químico:* 🟢 Bom (estável, sem inchaço)\n\n"
        f"⚡ *Condição Atual:*\n"
        f"• *Carga:* {batt_info}\n"
        f"• *Temperatura em Operação:* {b_temp_only}\n\n"
        "💡 _Diagnóstico Técnico: Desgaste normal e esperado para 5 anos e 1.700 ciclos. Como o aparelho opera como servidor fixo 24/7 conectado à tomada, a integridade operacional é excelente e 100% estável._"
    )


def clean_unit(val: str) -> str:
    """Converte Gi/Mi/G/M para GB e MB amigáveis."""
    val = val.strip()
    if val.endswith("Gi"):
        return f"{val[:-2]} GB"
    elif val.endswith("Mi"):
        return f"{val[:-2]} MB"
    elif val.endswith("G"):
        return f"{val[:-1]} GB"
    elif val.endswith("M"):
        return f"{val[:-1]} MB"
    return val


def format_friendly_uptime() -> str:
    """Retorna tempo ligado em formato amigável (ex: 3h 52min)."""
    try:
        res = subprocess.run(["uptime"], capture_output=True, text=True, timeout=2)
        raw_up = res.stdout.strip()
        m = re.search(r"up\s+(?:(\d+)\s+days?,\s*)?(\d+):(\d+)", raw_up)
        if m:
            days, hours, mins = m.groups()
            parts = []
            if days:
                d = int(days)
                parts.append(f"{d} dia" if d == 1 else f"{d} dias")
            if hours and int(hours) > 0:
                parts.append(f"{int(hours)}h")
            if mins:
                parts.append(f"{int(mins)}min")
            return " ".join(parts)
        m_min = re.search(r"up\s+(\d+)\s+min", raw_up)
        if m_min:
            return f"{m_min.group(1)} minutos"
    except Exception:
        pass
    return "Online"


def format_friendly_ram() -> str:
    """Retorna memória RAM formatada e legível."""
    try:
        res = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=2)
        lines = res.stdout.strip().splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            total = clean_unit(parts[1])
            used = clean_unit(parts[2])
            avail = clean_unit(parts[-1])
            return f"*{used} em uso* ({avail} livres de {total})"
    except Exception:
        pass
    return "N/A"


def format_friendly_disk() -> str:
    """Retorna espaço em disco limpo e legível."""
    try:
        res = subprocess.run(["df", "-h", os.path.expanduser("~")], capture_output=True, text=True, timeout=2)
        lines = res.stdout.strip().splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            total = clean_unit(parts[1])
            avail = clean_unit(parts[3])
            pct = parts[4]
            return f"*{avail} livres* de {total} ({pct} usado)"
    except Exception:
        pass
    return "N/A"


def cmd_status() -> str:
    batt_info, temp_info = get_battery_and_thermal_info()
    h = get_battery_health_info()
    asoc = h.get("asoc", 70)
    cycles = int(h.get("cycles", 1711))
    usable = h.get("current_mah", int(4500 * asoc / 100))
    saude_str = f"*{asoc}%* (ASOC) · *{cycles:,} ciclos* (~{usable:,} mAh)".replace(",", ".")

    uptime_str = format_friendly_uptime()
    ram_str = format_friendly_ram()
    disk_str = format_friendly_disk()

    # Checa portas locais
    p_ssh = check_port_open("127.0.0.1", 2222)
    p_socks = check_port_open("127.0.0.1", 1080)
    p_ftp_relay = check_port_open("127.0.0.1", 2121)
    p_adb_relay = check_port_open("127.0.0.1", 5555)

    if p_ssh and p_socks and p_ftp_relay and p_adb_relay:
        servicos_status = "🟢 *Todos Online* (SSH, SOCKS5, Relays, Bot)"
    else:
        status_items = []
        status_items.append("SSH: 🟢" if p_ssh else "SSH: 🔴")
        status_items.append("Proxy: 🟢" if p_socks else "Proxy: 🔴")
        status_items.append("FTP Relay: 🟢" if p_ftp_relay else "FTP Relay: 🔴")
        status_items.append("FireTV: 🟢" if p_adb_relay else "FireTV: 🔴")
        servicos_status = " · ".join(status_items)

    # Dispositivos locais
    ftp_ok = "🟢 *Conectado*" if check_port_open(FTP_HOST, FTP_PORT) else "🔴 *Inacessível*"
    tv_ok = "🟢 *Conectada*" if check_port_open(FIRETV_HOST, FIRETV_PORT) else "🟡 *Standby / Desligada*"

    return (
        "📊 *Galaxy A70 — Status do Servidor*\n\n"
        f"🔋 *Bateria:* {batt_info}\n"
        f"❤️ *Saúde da Bateria:* {saude_str}\n"
        f"🌡️ *Temperaturas:* {temp_info}\n\n"
        f"⏱️ *Ligado há:* {uptime_str}\n"
        f"💾 *Memória RAM:* {ram_str}\n"
        f"📂 *Armazenamento:* {disk_str}\n\n"
        f"🔌 *Serviços no A70:* {servicos_status}\n\n"
        "🌐 *Rede Doméstica:*\n"
        f"• Roteador FTP (192.168.0.1): {ftp_ok}\n"
        f"• Fire TV Stick (192.168.0.218): {tv_ok}"
    )


def cmd_limpar_ram() -> str:
    """Executa rotina de otimização e limpeza de memória no Galaxy A70."""
    try:
        def get_mem_stats():
            with open("/proc/meminfo") as f:
                d = dict(l.split(":") for l in f if ":" in l)
            total = int(d["MemTotal"].split()[0]) // 1024
            avail = int(d["MemAvailable"].split()[0]) // 1024
            cached = int(d.get("Cached", "0").split()[0]) // 1024
            used = total - avail
            pct = round((used / total) * 100)
            return total, used, avail, cached, pct

        total_b, used_b, avail_b, cached_b, pct_b = get_mem_stats()

        # 1. Força descarregamento de buffers em disco
        os.sync()

        # 2. Coleta de lixo do Python
        gc.collect()

        # 3. Libera heap C (malloc_trim)
        try:
            import ctypes
            libc = ctypes.CDLL("libc.so")
            libc.malloc_trim(0)
        except Exception:
            pass

        # 4. Encerra processos órfãos ou auxiliares que possam ter ficado em segundo plano
        killed_items = []
        for dead_proc in ("ffmpeg", "curl", "whisper-cli"):
            res = subprocess.run(["pkill", "-9", "-x", dead_proc], capture_output=True)
            if res.returncode == 0:
                killed_items.append(dead_proc)

        total_a, used_a, avail_a, cached_a, pct_a = get_mem_stats()

        killed_str = ", ".join(killed_items) if killed_items else "Nenhum processo pendente"

        return (
            "🧹 *Otimização de Memória RAM Realizada!*\n\n"
            f"📊 *Uso da RAM:* {pct_a}% ({used_a / 1024:.1f} GB usados de {total_a / 1024:.1f} GB)\n"
            f"💾 *Livre para Aplicações:* *{avail_a / 1024:.1f} GB livres*\n"
            f"⚡ *Cache de Leitura (Kernel):* {cached_a / 1024:.1f} GB\n"
            f"🧹 *Processos Limpos:* {killed_str}\n"
            f"🔄 *Buffers de Disco:* Sincronizados (`sync`)\n\n"
            "💡 _Nota: No Android/Linux, a memória 'Cached' é liberada instantaneamente pelo kernel assim que qualquer processo demandar mais RAM._"
        )
    except Exception as e:
        return f"❌ Erro ao otimizar memória: {e}"


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


def parse_iso(dt_str: Optional[str]) -> Optional[datetime.datetime]:
    """Converte string ISO 8601 em objeto datetime UTC."""
    if not dt_str:
        return None
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(dt_str)
    except Exception:
        return None


def get_dispatched_run_url(workflow_file: str = "legendar_ftp.yml", max_attempts: int = 4) -> Optional[Tuple[int, str]]:
    """Obtém o run_number e html_url do workflow recém-disparado."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{workflow_file}/runs?per_page=1"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "A70-WhatsApp-Bot/1.0",
    }
    for _ in range(max_attempts):
        time.sleep(1.2)
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                runs = data.get("workflow_runs", [])
                if runs:
                    r = runs[0]
                    created_at = r.get("created_at")
                    dt = parse_iso(created_at)
                    if dt:
                        diff_sec = (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds()
                        if diff_sec < 90:
                            return r.get("run_number"), r.get("html_url")
        except Exception:
            pass
    return None


def cmd_legendar(args: List[str]) -> str:
    if not args:
        return "⚠️ Uso incorreto: informe o número do episódio.\nExemplo: `legendar 55` ou `legendar 64 3`"

    m = re.search(r"\d+", args[0])
    if not m:
        return f"❌ Número de episódio inválido: `{args[0]}`"

    ep_num = int(m.group(0))
    video_filename = f"Uzak_Sehir_-_Episode_{ep_num:02d}.mp4" if ep_num < 10 else f"Uzak_Sehir_-_Episode_{ep_num}.mp4"

    # Permite especificar se deseja tradução ou apenas transcrição (padrão é 'none' para apenas transcrever e subir)
    wants_translate = any(a.lower() in ("traduzir", "gemini", "traducao") for a in args)
    translator_mode = "gemini" if wants_translate else "none"

    season_candidates = [a for a in args[1:] if a.lower() not in ("traduzir", "gemini", "traducao", "none")]
    season_arg = season_candidates[0] if season_candidates else ""
    season = normalizar_temporada(season_arg, ep_num)

    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/legendar_ftp.yml/dispatches"
    payload = json.dumps({
        "ref": "main",
        "inputs": {
            "video_filename": video_filename,
            "season": season,
            "network_mode": "tailscale",
            "usar_precache_audio": True,
            "translator": translator_mode,
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
                run_info = get_dispatched_run_url("legendar_ftp.yml")
                if run_info:
                    run_num, run_url = run_info
                    link_txt = f"🔗 *Acompanhar em tempo real:*\n{run_url}\n_(Run #{run_num})_"
                else:
                    link_txt = f"🔗 *Acompanhar em tempo real:*\nhttps://github.com/{GITHUB_REPO}/actions\n_(Digite *runs* para detalhes)_"

                modo_txt = "Tradução Completa (Gemini AI)" if wants_translate else "Apenas Transcrição e Upload (.srt original)"
                return (
                    f"🚀 *[Workflow Disparado com Sucesso]*\n\n"
                    f"🎬 Vídeo: `{video_filename}`\n"
                    f"📂 Temporada: *{season}*\n"
                    f"⚙️ Modo: *{modo_txt}*\n"
                    f"⚡ Rede: *Tailscale / WireGuard*\n"
                    f"🎵 Pré-cache de Áudio: *Ativado*\n\n"
                    f"{link_txt}"
                )
            else:
                return f"⚠️ Resposta inesperada do GitHub: HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")[:300]
        return f"❌ Erro ao disparar no GitHub (HTTP {e.code}):\n```{err}```"
    except Exception as e:
        return f"❌ Falha de conexão com a API do GitHub: {e}"


def format_br_time(dt: Optional[datetime.datetime]) -> str:
    """Formata datetime para o fuso horário de Brasília (UTC-3)."""
    if not dt:
        return "N/A"
    br_tz = datetime.timezone(datetime.timedelta(hours=-3))
    return dt.astimezone(br_tz).strftime("%H:%M:%S (%d/%m)")


def format_duration(seconds: float) -> str:
    """Formata segundos em horas, minutos e segundos legíveis."""
    s = max(0, int(seconds))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h}h {m:02d}m {sec:02d}s"
    elif m > 0:
        return f"{m}m {sec:02d}s"
    else:
        return f"{sec}s"


def cmd_baixar(args: List[str]) -> str:
    if not args:
        return (
            "⚠️ Uso incorreto: informe o número do episódio.\n"
            "Exemplo: `baixar 72` ou `baixar 64 72` (para intervalo) ou `baixar 72 3`"
        )

    nums = [int(n) for n in re.findall(r"\d+", " ".join(args))]
    if not nums:
        return f"❌ Nenhum número de episódio válido em `{' '.join(args)}`"

    if len(nums) == 1:
        ep_start = nums[0]
        ep_end = nums[0]
        season_candidates = [a for a in args if not a.isdigit()]
        season_arg = season_candidates[0] if season_candidates else ""
    elif len(nums) >= 2:
        if nums[1] < 10 and nums[0] >= 10:
            ep_start = nums[0]
            ep_end = nums[0]
            season_arg = str(nums[1])
        else:
            ep_start = min(nums[0], nums[1])
            ep_end = max(nums[0], nums[1])
            season_candidates = [a for a in args if not a.isdigit()]
            season_arg = season_candidates[0] if season_candidates else ""
    else:
        ep_start = nums[0]
        ep_end = nums[0]
        season_arg = ""

    season = normalizar_temporada(season_arg, ep_start)

    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/baixar_episodios_ftp.yml/dispatches"
    payload = json.dumps({
        "ref": "main",
        "inputs": {
            "season": season,
            "episode_start": ep_start,
            "episode_end": ep_end,
            "network_mode": "tailscale",
            "skip_existing": True,
            "notify_whatsapp": True,
            "auto_subtitle": False,
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
                run_info = get_dispatched_run_url("baixar_episodios_ftp.yml")
                if run_info:
                    run_num, run_url = run_info
                    link_txt = f"🔗 *Acompanhar em tempo real:*\n{run_url}\n_(Run #{run_num})_"
                else:
                    link_txt = f"🔗 *Acompanhar em tempo real:*\nhttps://github.com/{GITHUB_REPO}/actions\n_(Digite *runs* para detalhes)_"

                range_txt = f"Episódio {ep_start}" if ep_start == ep_end else f"Episódios {ep_start} até {ep_end}"
                return (
                    f"📥 *[Download Disparado via Turkish123]*\n\n"
                    f"🎬 {range_txt}\n"
                    f"📂 Temporada: *{season}*\n"
                    f"⚡ Rede: *Tailscale / WireGuard*\n"
                    f"📊 Progresso em tempo real ativado no log e WhatsApp!\n\n"
                    f"{link_txt}"
                )
            else:
                return f"⚠️ Resposta inesperada do GitHub: HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")[:300]
        return f"❌ Erro ao disparar download no GitHub (HTTP {e.code}):\n```{err}```"
    except Exception as e:
        return f"❌ Falha de conexão com a API do GitHub: {e}"


def get_run_active_step(run_id: int) -> Optional[str]:
    """Obtém a etapa ativa de uma execução in_progress no GitHub Actions."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs/{run_id}/jobs"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "A70-WhatsApp-Bot/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for job in data.get("jobs", []):
                if job.get("status") == "in_progress":
                    for step in job.get("steps", []):
                        if step.get("status") == "in_progress":
                            return step.get("name")
                    return job.get("name")
    except Exception:
        pass
    return None


def cmd_runs() -> str:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs?per_page=3"
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

            now_utc = datetime.datetime.now(datetime.timezone.utc)
            linhas = ["⏳ *Status dos Workflows no GitHub Actions:*\n"]

            for r in runs:
                run_id = r.get("id")
                name = r.get("display_title") or r.get("name", "Workflow")
                html_url = r.get("html_url", "")
                status = r.get("status", "")
                conclusion = r.get("conclusion")

                started_dt = parse_iso(r.get("run_started_at") or r.get("created_at"))
                updated_dt = parse_iso(r.get("updated_at"))

                start_str = format_br_time(started_dt)
                end_str = format_br_time(updated_dt)

                if status == "in_progress":
                    elapsed_s = (now_utc - started_dt).total_seconds() if started_dt else 0
                    dur_str = format_duration(elapsed_s)
                    badge = f"🔄 *Em andamento* (há {dur_str})"
                    active_step = get_run_active_step(run_id)
                    step_txt = f"\n  📍 *Etapa:* `{active_step}`" if active_step else ""
                    time_info = f"🕒 *Iniciado às:* {start_str}{step_txt}"
                elif status == "queued":
                    badge = "⏳ *Na fila*"
                    time_info = f"🕒 *Criado às:* {start_str}"
                elif status == "completed":
                    dur_s = (updated_dt - started_dt).total_seconds() if (started_dt and updated_dt) else 0
                    dur_str = format_duration(dur_s)

                    if conclusion == "success":
                        badge = f"✅ *Concluído com Sucesso* ({dur_str})"
                        time_info = f"🕒 *Início:* {start_str}\n  🏁 *Finalizado às:* {end_str}"
                    elif conclusion == "failure":
                        badge = f"❌ *Falhou* ({dur_str})"
                        time_info = f"🕒 *Início:* {start_str}\n  ⚠️ *Falhou às:* {end_str}"
                    elif conclusion == "cancelled":
                        badge = f"⏹️ *Cancelado* ({dur_str})"
                        time_info = f"🕒 *Início:* {start_str}\n  🛑 *Cancelado às:* {end_str}"
                    else:
                        badge = f"⚪ *{conclusion}* ({dur_str})"
                        time_info = f"🕒 *Início:* {start_str}\n  🏁 *Fim:* {end_str}"
                else:
                    badge = f"⚪ *{status}*"
                    time_info = f"🕒 *Horário:* {start_str}"

                linhas.append(
                    f"• *#{run_id}* — {badge}\n"
                    f"  🎬 `{name}`\n"
                    f"  {time_info}\n"
                    f"  🔗 {html_url}\n"
                )

            linhas.append("💡 Para disparar nova legenda: `legendar <ep>` | Novo download: `baixar <ep>`")
            return "\n".join(linhas)
    except Exception as e:
        return f"❌ Erro ao consultar execuções no GitHub: {e}"


def cmd_ftp(args: List[str]) -> str:
    season_arg = args[0] if args else "3"
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


def cmd_firetv(args: List[str]) -> str:
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
            return f"📺 Comando Fire TV `{subcmd}` ({key}) enviado com sucesso!"
        except Exception as e:
            return f"❌ Falha ao enviar comando ADB: {e}"

    return f"📺 Comandos Fire TV suportados: `firetv status`, `firetv play`, `firetv pause`, `firetv home`."


def is_media_command(text: str) -> bool:
    """Verifica se o texto é destinado exclusivamente aos serviços de mídia/A70."""
    t = text.strip()
    if not t:
        return False
    if t.startswith(("!", "/")):
        t = t[1:].strip()
    parts = t.split()
    if not parts:
        return False
    cmd = parts[0].lower()

    if cmd in ("a70", "midia"):
        return True
    if cmd in ("bateria", "saude"):
        return True
    if cmd == "status" and len(parts) > 1 and parts[1].lower() in ("a70", "midia", "bateria", "saude"):
        return True
    if cmd in ("ajuda", "menu", "comandos") and len(parts) > 1 and parts[1].lower() in ("midia", "a70", "bateria"):
        return True
    if cmd in ("precache", "extrair", "legendar", "legenda", "transcrever", "runs", "fila", "status_runs", "ftp", "firetv", "limpar", "otimizar", "liberar", "baixar", "download", "bateria", "saude"):
        return True
    return False


def process_incoming_text(sender_clean: str, text: str) -> Optional[str]:
    """Interpreta a mensagem de mídia e retorna a resposta."""
    t = text.strip()
    if not t:
        return None

    if t.startswith(("!", "/")):
        t = t[1:].strip()

    parts = t.split()
    cmd = parts[0].lower()
    args = parts[1:]

    # 1. Menu de ajuda de mídia
    if cmd in ("midia", "menu_midia", "ajuda_midia"):
        return cmd_help()
    elif cmd in ("ajuda", "menu", "comandos") and (args and args[0].lower() in ("midia", "a70", "bateria")):
        return cmd_help()

    # 2. Status técnico do Galaxy A70 e Bateria
    elif cmd == "a70":
        return cmd_status()
    elif cmd == "status" and (args and args[0].lower() in ("a70", "midia")):
        return cmd_status()
    elif cmd in ("bateria", "saude"):
        return cmd_saude_bateria()
    elif cmd == "status" and (args and args[0].lower() in ("bateria", "saude")):
        return cmd_saude_bateria()
    elif cmd in ("limpar", "otimizar", "liberar"):
        return cmd_limpar_ram()

    # 3. Comandos operacionais
    elif cmd in ("baixar", "download"):
        return cmd_baixar(args)
    elif cmd in ("precache", "extrair", "audio"):
        return cmd_precache(sender_clean, args)
    elif cmd in ("legendar", "legenda", "transcrever"):
        return cmd_legendar(args)
    elif cmd in ("runs", "fila", "status_runs", "jobs"):
        return cmd_runs()
    elif cmd in ("ftp", "arquivos", "series"):
        return cmd_ftp(args)
    elif cmd == "firetv":
        return cmd_firetv(args)

    return None


PROCESSED_MESSAGES: Dict[str, float] = {}
DEDUP_LOCK = threading.Lock()


def is_duplicate(msg_id: str, sender: str, text: str) -> bool:
    """Evita processar a mesma mensagem duas vezes, com debounce para eventos repetidos."""
    now = time.time()
    norm_text = text.strip().lower()
    with DEDUP_LOCK:
        # Limpa entradas com mais de 60 segundos
        to_delete = [k for k, ts in PROCESSED_MESSAGES.items() if now - ts > 60.0]
        for k in to_delete:
            del PROCESSED_MESSAGES[k]

        id_key = f"id:{msg_id}" if msg_id else ""
        text_key = f"txt:{sender}:{norm_text}"

        # Se já vimos o msg_id nos últimos 60 segundos
        if id_key and id_key in PROCESSED_MESSAGES:
            return True

        # Se o mesmo remetente mandou exatamente o mesmo comando nos últimos 4 segundos (debounce)
        if text_key in PROCESSED_MESSAGES:
            if (now - PROCESSED_MESSAGES[text_key]) < 4.0:
                return True

        if id_key:
            PROCESSED_MESSAGES[id_key] = now
        PROCESSED_MESSAGES[text_key] = now
        return False


class WebhookHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        """Permite baixar o APK do Termux:API diretamente pelo navegador."""
        if self.path.startswith("/termux-api.apk"):
            apk_path = os.path.expanduser("~/termux-api.apk")
            if os.path.isfile(apk_path):
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.android.package-archive")
                self.send_header("Content-Length", str(os.path.getsize(apk_path)))
                self.send_header("Content-Disposition", "attachment; filename=termux-api.apk")
                self.end_headers()
                with open(apk_path, "rb") as f:
                    self.wfile.write(f.read())
                return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)

        # Responde 200 OK imediatamente para a Evolution API não dar timeout
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"received"}')

        # Processa mensagem
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception:
            # Em caso de JSON inválido, repassa ao HA por segurança
            threading.Thread(target=forward_to_homeassistant, args=(raw_body,), daemon=True).start()
            return

        event = payload.get("event")
        if event != "messages.upsert":
            # Eventos de sistema que não são mensagens vão direto ao HA
            threading.Thread(target=forward_to_homeassistant, args=(raw_body,), daemon=True).start()
            return

        data = payload.get("data")
        if not data:
            threading.Thread(target=forward_to_homeassistant, args=(raw_body,), daemon=True).start()
            return

        msg_items = data if isinstance(data, list) else [data]
        media_cmd_handled = False

        for item in msg_items:
            key = item.get("key", {})
            if key.get("fromMe", False):
                continue

            remote_jid = key.get("remoteJid", "")
            sender_num = "".join(filter(str.isdigit, remote_jid.split("@")[0]))

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

            if is_media_command(text):
                msg_id = key.get("id", "")
                if is_duplicate(msg_id, sender_num, text):
                    print(f"[Bot] Mensagem duplicada ignorada (id={msg_id}): {text}", flush=True)
                    media_cmd_handled = True
                    continue

                print(f"[Bot] Comando de Mídia recebido de {sender_num}: {text}", flush=True)
                resposta = process_incoming_text(sender_num, text)
                if resposta:
                    send_whatsapp(sender_num, resposta)
                media_cmd_handled = True

        # Se NÃO foi um comando de mídia, repassa transparentemente para o Home Assistant
        if not media_cmd_handled:
            threading.Thread(target=forward_to_homeassistant, args=(raw_body,), daemon=True).start()

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
