#!/usr/bin/env python3
"""
a70top - High-Performance, Beautiful Per-Core Terminal Monitor for Galaxy A70
Bypasses Android SELinux /proc/stat restrictions by reading kernel cpuidle & cpufreq sysfs nodes directly.
Displays all 8 CPU cores individually with real-time utilization %, frequencies, thermals, RAM,
gateway services, and top processes.
"""

import os
import sys
import time
import glob
import select
import termios
import tty
import socket
import re
from typing import Any, Dict, List, Tuple

# Paleta ANSI 256 cores
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_RED = "\033[38;5;196m"
C_GREEN = "\033[38;5;46m"
C_YELLOW = "\033[38;5;226m"
C_BLUE = "\033[38;5;39m"
C_CYAN = "\033[38;5;51m"
C_MAGENTA = "\033[38;5;207m"
C_WHITE = "\033[38;5;255m"
C_GRAY = "\033[38;5;244m"
C_BG_BAR = "\033[38;5;238m"

THERMAL_ROOT = "/sys/class/thermal"
HEALTH_FILES = [os.path.expanduser(p) for p in (
    "~/.battery_health_a70.json", "~/.battery_health.json"
)]


def get_thermal_temp(kind: str) -> float | None:
    """Find sensor zones by type; thermal_zone indexes vary across devices."""
    try:
        for zone in glob.glob(os.path.join(THERMAL_ROOT, "thermal_zone*")):
            try:
                with open(os.path.join(zone, "type")) as f:
                    zone_type = f.read().strip().lower()
                if kind == "battery":
                    matches = "battery" in zone_type or "batt" in zone_type
                else:
                    tokens = set(re.split(r"[^a-z0-9]+", zone_type))
                    matches = any(token in zone_type for token in ("cpu", "soc", "package")) or "ap" in tokens
                if not matches:
                    continue
                with open(os.path.join(zone, "temp")) as f:
                    value = int(f.read().strip())
                return round(value / (1000.0 if abs(value) >= 1000 else 1.0), 1)
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return None


def get_cpu_temp() -> float | None:
    return get_thermal_temp("cpu")


def get_batt_temp() -> float | None:
    return get_thermal_temp("battery")


def get_batt_health_info() -> str:
    import json
    for health_file in HEALTH_FILES:
        try:
            with open(health_file, "r") as f:
                data = json.load(f)
            health = data.get("asoc_pct", data.get("asoc"))
            cycles = data.get("charge_cycles", data.get("cycles"))
            parts = []
            if health is not None:
                parts.append(f"Saúde {health}%")
            if cycles is not None:
                parts.append(f"{cycles}c")
            if parts:
                return " · ".join(parts)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return "Saúde indisponível"


def is_cpu_online(cpu_idx: int) -> bool:
    online_path = f"/sys/devices/system/cpu/cpu{cpu_idx}/online"
    try:
        with open(online_path) as f:
            return f.read().strip() != "0"
    except OSError:
        # cpu0 normally has no online file; the directory indicates its presence.
        return os.path.isdir(f"/sys/devices/system/cpu/cpu{cpu_idx}")


def get_cpu_idle_us(cpu_idx: int) -> int:
    total_us = 0
    for path in glob.glob(f"/sys/devices/system/cpu/cpu{cpu_idx}/cpuidle/state*/time"):
        try:
            with open(path) as f:
                total_us += int(f.read().strip())
        except Exception:
            pass
    return total_us


def get_cpu_freq_mhz(cpu_idx: int) -> Tuple[int, str]:
    freq_path = f"/sys/devices/system/cpu/cpu{cpu_idx}/cpufreq/scaling_cur_freq"
    online_path = f"/sys/devices/system/cpu/cpu{cpu_idx}/online"
    is_online = True
    try:
        with open(online_path) as f:
            if f.read().strip() == "0":
                is_online = False
    except Exception:
        pass

    if not is_online:
        return 0, "offline"

    try:
        with open(freq_path) as f:
            mhz = int(f.read().strip()) // 1000
            return mhz, f"{mhz} MHz"
    except Exception:
        return 0, "N/A"


def get_mem_info() -> Dict[str, float]:
    mem = {"total_gb": 0.0, "used_gb": 0.0, "free_gb": 0.0, "swap_total_mb": 0.0, "swap_used_mb": 0.0}
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        data = {}
        for line in lines:
            parts = line.split(":")
            if len(parts) == 2:
                key = parts[0].strip()
                val = parts[1].strip().split()[0]
                data[key] = int(val)
        total_kb = data.get("MemTotal", 0)
        avail_kb = data.get("MemAvailable", data.get("MemFree", 0))
        used_kb = max(0, total_kb - avail_kb)
        swap_total_kb = data.get("SwapTotal", 0)
        swap_free_kb = data.get("SwapFree", 0)
        swap_used_kb = max(0, swap_total_kb - swap_free_kb)

        mem["total_gb"] = round(total_kb / 1024 / 1024, 2)
        mem["used_gb"] = round(used_kb / 1024 / 1024, 2)
        mem["free_gb"] = round(avail_kb / 1024 / 1024, 2)
        mem["swap_total_mb"] = round(swap_total_kb / 1024, 0)
        mem["swap_used_mb"] = round(swap_used_kb / 1024, 0)
    except Exception:
        pass
    return mem


def probe_port(port: int, timeout: float = 0.15) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except Exception:
        return False


def get_top_termux_processes(limit: int = 6) -> List[Dict[str, Any]]:
    import subprocess
    procs = []
    try:
        out = subprocess.check_output(["ps", "-u", os.environ.get("USER", "u0_a615"), "-o", "pid,vsz,rss,comm,args"], stderr=subprocess.DEVNULL).decode()
        lines = out.strip().split("\n")[1:]
        for line in lines:
            parts = line.split(None, 4)
            if len(parts) >= 4:
                pid = parts[0]
                rss_kb = int(parts[2]) if parts[2].isdigit() else 0
                cmd = parts[4] if len(parts) >= 5 else parts[3]
                if "a70top" in cmd or "ps -u" in cmd:
                    continue
                cmd_short = cmd.replace("/data/data/com.termux/files/usr/bin/", "").replace("/data/data/com.termux/files/home/", "")
                procs.append({
                    "pid": pid,
                    "rss_mb": round(rss_kb / 1024, 1),
                    "cmd": cmd_short[:35],
                })
        procs.sort(key=lambda x: x["rss_mb"], reverse=True)
    except Exception:
        pass
    return procs[:limit]


def make_bar(percent: float, width: int = 16) -> str:
    clamped = max(0.0, min(100.0, percent))
    filled = int(round((clamped / 100.0) * width))
    empty = width - filled
    
    if clamped < 50.0:
        bar_color = C_GREEN
    elif clamped < 80.0:
        bar_color = C_YELLOW
    else:
        bar_color = C_RED

    return f"{bar_color}{'█' * filled}{C_BG_BAR}{'░' * empty}{C_RESET}"


def render_dashboard(idle_prev: List[int], time_prev: float) -> Tuple[List[int], float]:
    time_now = time.time()
    online = [is_cpu_online(i) for i in range(8)]
    idle_now = [get_cpu_idle_us(i) if online[i] else 0 for i in range(8)]
    dt_us = max(1.0, (time_now - time_prev) * 1_000_000)

    # Per-core utilization
    utils = []
    freqs = []
    for i in range(8):
        d_idle = max(0, idle_now[i] - idle_prev[i])
        u = max(0.0, min(100.0, 100.0 * (1.0 - (d_idle / dt_us)))) if online[i] else 0.0
        utils.append(u)
        freqs.append(get_cpu_freq_mhz(i))

    cpu_t = get_cpu_temp()
    batt_t = get_batt_temp()
    health_str = get_batt_health_info()
    mem = get_mem_info()

    # Checagem de Servicos
    svc_ssh = probe_port(2222)
    svc_socks = probe_port(1080)
    svc_ftp = probe_port(2121)
    svc_firetv = probe_port(5555)
    svc_bot = probe_port(8088)

    buf = []
    # Clear screen and move cursor home
    buf.append("\033[H\033[J")
    
    # 1. Cabecalho
    buf.append(f"{C_BOLD}{C_CYAN}╭────────────────────────────────────────────────────────────────────────╮{C_RESET}")
    buf.append(f"{C_BOLD}{C_CYAN}│ {C_WHITE}Galaxy A70 (Snapdragon 675 · Kryo 460 · 8 Cores · 6GB RAM){C_CYAN}               │{C_RESET}")
    
    temp_cpu_col = C_GRAY if cpu_t is None else (C_GREEN if cpu_t < 45 else (C_YELLOW if cpu_t < 65 else C_RED))
    temp_bat_col = C_GRAY if batt_t is None else (C_GREEN if batt_t < 35 else (C_YELLOW if batt_t < 42 else C_RED))
    cpu_temp_label = f"{cpu_t}°C" if cpu_t is not None else "N/D"
    batt_temp_label = f"{batt_t}°C" if batt_t is not None else "N/D"
    
    sub_line = (
        f"│ CPU: {temp_cpu_col}{cpu_temp_label}{C_RESET} │ "
        f"Bat: {temp_bat_col}{batt_temp_label}{C_RESET} ({health_str}) │ "
        f"Cores: {C_GREEN}{sum(online)} Ativos{C_RESET} │"
    )
    buf.append(f"{C_CYAN}{sub_line:<82}│{C_RESET}")
    buf.append(f"{C_BOLD}{C_CYAN}├────────────────────────────────────────────────────────────────────────┤{C_RESET}")

    # 2. Monitor de Processadores (Cores 0 a 7 individualmente)
    buf.append(f"{C_CYAN}│ {C_BOLD}{C_YELLOW}PROCESSADORES (UTILIZACAO & CLOCKS INDIVIDUAIS){C_RESET}{C_CYAN}                        │{C_RESET}")
    
    # Renderiza em 4 linhas com 2 colunas cada
    for row in range(4):
        c_left = row
        c_right = row + 4
        
        # Coluna Esquerda (cpu0 a cpu3)
        u_l = utils[c_left]
        mhz_l, str_l = freqs[c_left]
        tag_l = "Silver"
        bar_l = make_bar(u_l, width=12)
        col_left = f"CPU{c_left} [{bar_l}] {u_l:5.1f}% {str_l:>8} ({tag_l})" if online[c_left] else f"CPU{c_left} offline"

        # Coluna Direita (cpu4 a cpu7)
        u_r = utils[c_right]
        mhz_r, str_r = freqs[c_right]
        tag_r = "Gold ⚡" if c_right >= 6 else "Silver"
        bar_r = make_bar(u_r, width=12)
        col_right = f"CPU{c_right} [{bar_r}] {u_r:5.1f}% {str_r:>8} ({tag_r})" if online[c_right] else f"CPU{c_right} offline"

        line = f"│ {col_left}  │ {col_right} │"
        buf.append(line)

    buf.append(f"{C_BOLD}{C_CYAN}├────────────────────────────────────────────────────────────────────────┤{C_RESET}")

    # 3. Memoria e Swap
    mem_pct = round((mem["used_gb"] / max(mem["total_gb"], 0.001)) * 100, 1)
    swap_pct = round((mem["swap_used_mb"] / max(mem["swap_total_mb"], 0.001)) * 100, 1)
    bar_ram = make_bar(mem_pct, width=16)
    bar_swap = make_bar(swap_pct, width=16)

    buf.append(f"{C_CYAN}│ {C_BOLD}{C_MAGENTA}MEMORIA & SWAP{C_RESET}{C_CYAN}                                                          │{C_RESET}")
    buf.append(f"│ RAM:  [{bar_ram}] {mem_pct:5.1f}% ({mem['used_gb']}G / {mem['total_gb']}G)                               │")
    buf.append(f"│ Swap: [{bar_swap}] {swap_pct:5.1f}% ({int(mem['swap_used_mb'])}M / {int(mem['swap_total_mb'])}M)                             │")

    buf.append(f"{C_BOLD}{C_CYAN}├────────────────────────────────────────────────────────────────────────┤{C_RESET}")

    # 4. Servicos Locais e Relays
    icon = lambda ok: f"{C_GREEN}🟢 Online{C_RESET}" if ok else f"{C_RED}🔴 Offline{C_RESET}"
    svc_line = (
        f"│ SSH:{icon(svc_ssh)}  "
        f"SOCKS5:{icon(svc_socks)}  "
        f"FTP:{icon(svc_ftp)}  "
        f"FireTV:{icon(svc_firetv)}  "
        f"Bot:{icon(svc_bot)} │"
    )
    buf.append(f"{C_CYAN}│ {C_BOLD}{C_BLUE}SERVICOS & GATEWAY RELAYS{C_RESET}{C_CYAN}                                              │{C_RESET}")
    buf.append(svc_line)

    buf.append(f"{C_BOLD}{C_CYAN}├────────────────────────────────────────────────────────────────────────┤{C_RESET}")

    # 5. Top Processos do Termux
    buf.append(f"{C_CYAN}│ {C_BOLD}{C_WHITE}TOP PROCESSOS TERMUX{C_RESET}{C_CYAN} (Ordenado por Memoria){C_RESET}{C_CYAN}                             │{C_RESET}")
    buf.append(f"{C_CYAN}│ {C_DIM}PID    MEM (MB)   COMANDO{C_RESET}{C_CYAN}                                               │{C_RESET}")
    top_procs = get_top_termux_processes(limit=5)
    for p in top_procs:
        p_line = f"│ {p['pid']:<6} {p['rss_mb']:>7.1f}M   {p['cmd']:<45} │"
        buf.append(p_line)
    
    # Preenchimento se houver menos de 5
    for _ in range(5 - len(top_procs)):
        buf.append(f"│ {'':<68} │")

    buf.append(f"{C_BOLD}{C_CYAN}╰────────────────────────────────────────────────────────────────────────╯{C_RESET}")
    buf.append(f"{C_DIM} [q] Sair · [r] Atualizar · Intervalo: 1.0s · Kernel Sysfs Engine{C_RESET}")

    sys.stdout.write("\n".join(buf) + "\n")
    sys.stdout.flush()

    return idle_now, time_now


def main():
    # Suporte a snapshot unico (se chamado com -n 1 ou --once)
    once = "-n" in sys.argv or "--once" in sys.argv

    # Primeira leitura de telemetria
    t0 = time.time()
    idle0 = [get_cpu_idle_us(i) for i in range(8)]
    time.sleep(0.5)

    if once:
        render_dashboard(idle0, t0)
        return

    # Modo interativo continuo
    orig_settings = None
    fd = sys.stdin.fileno()
    is_tty = os.isatty(fd)

    if is_tty:
        orig_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)

    try:
        # Esconde cursor
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()

        prev_idle = idle0
        prev_time = t0

        while True:
            prev_idle, prev_time = render_dashboard(prev_idle, prev_time)

            # Espera 1.0s checando por input de teclado ('q' para sair)
            if is_tty:
                rlist, _, _ = select.select([sys.stdin], [], [], 1.0)
                if rlist:
                    ch = sys.stdin.read(1)
                    if ch in ("q", "Q", "\x03", "\x1b"):  # q ou Ctrl+C ou Esc
                        break
                    elif ch in ("r", "R"):
                        continue
            else:
                time.sleep(1.0)

    finally:
        # Restaura cursor e terminal
        sys.stdout.write("\033[?25h\033[m\n")
        sys.stdout.flush()
        if orig_settings and is_tty:
            termios.tcsetattr(fd, termios.TCSADRAIN, orig_settings)


if __name__ == "__main__":
    main()
