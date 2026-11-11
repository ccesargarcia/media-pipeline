#!/usr/bin/env python3
"""
Galaxy A70 Resource & Tunnel Monitor for Uptime Kuma (Hardened Edition)
Pushes Memory (RAM), Disk (Storage), Battery/Temperature, and Tailscale/WireGuard Tunnel
metrics to Uptime Kuma push monitors with high resilience and anti-doze protection.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

KUMA_RAM_URL = "https://monitor.luisices.com.br/api/push/A70RamPushToken2026X"
KUMA_DISK_URL = "https://monitor.luisices.com.br/api/push/A70DiskPushToken2026X"
KUMA_BATTERY_URL = "https://monitor.luisices.com.br/api/push/A70BatteryPushToken2026X"
KUMA_TUNNEL_URL = "https://monitor.luisices.com.br/api/push/A70WireGuardTunnelPushToken2026X"

# Limiares de alerta
RAM_MIN_AVAILABLE_MB = 250   # Alerta down se RAM livre < 250MB
DISK_MIN_FREE_GB = 4.0       # Alerta down se disco livre < 4GB
BATTERY_MAX_TEMP_C = 45.0    # Alerta down se temperatura da bateria > 45°C
CPU_MAX_TEMP_C = 80.0        # Alerta down se temperatura da CPU > 80°C
BATTERY_MIN_PCT_DISCHARGING = 15  # Alerta down se bateria < 15% fora da tomada

# Cache de bateria para evitar lentidão do binder IPC
_last_battery_time = 0
_cached_battery_data = {"pct": 100, "plug_str": "100% AC", "st_val": "FULL", "batt_temp": 26.5}


def push_metric(url: str, ok: bool, msg: str, ping_val: int) -> bool:
    try:
        params = urllib.parse.urlencode({
            "status": "up" if ok else "down",
            "msg": msg,
            "ping": max(1, int(ping_val)),
        })
        req = urllib.request.Request(
            f"{url}?{params}",
            headers={"User-Agent": "A70ResourceMonitor/2.1"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[ResourceMonitor] Erro push para {url}: {e}", flush=True)
        return False


def check_ram():
    """Lê /proc/meminfo e retorna (ok, msg, pct_usado)."""
    try:
        with open("/proc/meminfo", "r") as f:
            lines = dict(line.split(":") for line in f if ":" in line)
        total_kb = int(lines["MemTotal"].split()[0])
        avail_kb = int(lines["MemAvailable"].split()[0])
        used_kb = total_kb - avail_kb

        total_gb = total_kb / (1024 * 1024)
        used_gb = used_kb / (1024 * 1024)
        avail_gb = avail_kb / (1024 * 1024)
        avail_mb = avail_kb / 1024

        pct_used = max(1, min(100, round((used_kb / total_kb) * 100)))

        if avail_mb < RAM_MIN_AVAILABLE_MB or pct_used >= 95:
            ok = False
            msg = f"ALERTA RAM: {used_gb:.1f}GB/{total_gb:.1f}GB ({pct_used}% usada) | Pouca memória livre: {avail_mb:.0f}MB"
        else:
            ok = True
            msg = f"RAM: {used_gb:.1f}GB/{total_gb:.1f}GB ({pct_used}% usada) | {avail_gb:.1f}GB livres"

        return ok, msg, pct_used
    except Exception as e:
        return False, f"Erro leitura RAM: {e}", 0


def check_disk():
    """Lê os.statvfs e retorna (ok, msg, pct_usado)."""
    try:
        home_path = os.path.expanduser("~")
        st = os.statvfs(home_path)
        total_gb = (st.f_blocks * st.f_frsize) / (1024 ** 3)
        free_gb = (st.f_bavail * st.f_frsize) / (1024 ** 3)
        used_gb = total_gb - free_gb

        pct_used = max(1, min(100, round((used_gb / total_gb) * 100)))

        if free_gb < DISK_MIN_FREE_GB or pct_used >= 95:
            ok = False
            msg = f"ALERTA DISCO: {used_gb:.1f}GB/{total_gb:.0f}GB ({pct_used}% usado) | Restam apenas {free_gb:.1f}GB livres"
        else:
            ok = True
            msg = f"Disco: {used_gb:.1f}GB/{total_gb:.0f}GB ({pct_used}% usado) | {free_gb:.1f}GB livres"

        return ok, msg, pct_used
    except Exception as e:
        return False, f"Erro leitura Disco: {e}", 0


def check_battery():
    """Lê telemetria de bateria com fallback ultra-rápido para sysfs."""
    global _last_battery_time, _cached_battery_data
    now = time.time()

    if now - _last_battery_time > 120:
        try:
            res = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=2.0)
            if res.returncode == 0 and res.stdout.strip():
                b_data = json.loads(res.stdout.strip())
                pct = int(b_data.get("percentage", 100))
                st_val = b_data.get("status", "")
                plug = b_data.get("plugged", "")
                t = b_data.get("temperature")
                batt_temp = round(float(t), 1) if t is not None else None

                if st_val == "FULL" or pct == 100:
                    plug_str = "100% AC"
                elif "PLUGGED" in str(plug) or st_val == "CHARGING":
                    plug_str = "AC Carregando"
                elif st_val == "DISCHARGING":
                    plug_str = "Na Bateria"
                else:
                    plug_str = str(st_val or plug or "AC")

                _cached_battery_data = {
                    "pct": pct,
                    "plug_str": plug_str,
                    "st_val": st_val,
                    "batt_temp": batt_temp,
                }
                _last_battery_time = now
        except Exception:
            pass

    pct = _cached_battery_data["pct"]
    plug_str = _cached_battery_data["plug_str"]
    st_val = _cached_battery_data["st_val"]
    batt_temp = _cached_battery_data.get("batt_temp")
    cpu_temp = None

    try:
        with open("/sys/class/thermal/thermal_zone62/temp", "r") as f:
            batt_temp = round(int(f.read().strip()) / 1000, 1)
    except Exception:
        pass

    try:
        with open("/sys/class/thermal/thermal_zone18/temp", "r") as f:
            cpu_temp = round(int(f.read().strip()) / 1000, 1)
    except Exception:
        pass

    alerts = []
    if batt_temp is not None and batt_temp > BATTERY_MAX_TEMP_C:
        alerts.append(f"Alta temp bateria: {batt_temp}°C")
    if cpu_temp is not None and cpu_temp > CPU_MAX_TEMP_C:
        alerts.append(f"Alta temp CPU: {cpu_temp}°C")
    if st_val == "DISCHARGING" and pct < BATTERY_MIN_PCT_DISCHARGING:
        alerts.append(f"Bateria fraca: {pct}%")

    ok = len(alerts) == 0

    temp_parts = []
    if batt_temp is not None:
        temp_parts.append(f"Bat {batt_temp}°C")
    if cpu_temp is not None:
        temp_parts.append(f"CPU {cpu_temp}°C")
    temps_str = " · ".join(temp_parts) if temp_parts else "N/A"

    health_extra = ""
    try:
        h_file = os.path.expanduser("~/.battery_health.json")
        if os.path.isfile(h_file):
            with open(h_file, "r") as f:
                h_data = json.load(f)
                asoc = h_data.get("asoc")
                cycles = h_data.get("cycles")
                if asoc is not None:
                    health_extra = f" | Saúde: {asoc}% ({int(cycles)}c)"
    except Exception:
        pass

    if not ok:
        alert_text = "; ".join(alerts)
        msg = f"ALERTA BATERIA: {alert_text} | Nível: {pct}% ({plug_str}) | {temps_str}{health_extra}"
    else:
        msg = f"Bat: {pct}% ({plug_str}) | {temps_str}{health_extra}"

    return ok, msg, pct


def check_tunnel():
    """Verifica interface Tailscale tun0 (100.97.222.39), MagicDNS e portas da ponte."""
    try:
        res = subprocess.run(
            ["/system/bin/ip", "-4", "addr", "show", "dev", "tun0"],
            capture_output=True, text=True, timeout=2.0
        )
        if res.returncode != 0 or "100.97.222.39" not in res.stdout:
            return False, "Tailscale tun0 OFFLINE (100.97.222.39 ausente)", 0
    except Exception as e:
        return False, f"Erro checagem tun0: {e}", 0

    t0 = time.time()
    try:
        with socket.create_connection(("100.100.100.100", 53), timeout=3.0):
            pass
    except Exception:
        return False, "Tunel Tailscale sem trafego (100.100.100.100 inacessivel)", 0
    ping_ms = max(1, round((time.time() - t0) * 1000))

    for port in (2222, 1080, 2121):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5):
                pass
        except Exception:
            return False, f"Servico da ponte na porta {port} parado no A70", ping_ms

    return True, "OK: Tunel WireGuard/Tailscale (100.97.222.39) + SSH/SOCKS5/FTP Ativos", ping_ms


def run_cycle():
    ram_ok, ram_msg, ram_pct = check_ram()
    push_metric(KUMA_RAM_URL, ram_ok, ram_msg, ram_pct)

    disk_ok, disk_msg, disk_pct = check_disk()
    push_metric(KUMA_DISK_URL, disk_ok, disk_msg, disk_pct)

    bat_ok, bat_msg, bat_pct = check_battery()
    push_metric(KUMA_BATTERY_URL, bat_ok, bat_msg, bat_pct)

    tun_ok, tun_msg, tun_ping = check_tunnel()
    push_metric(KUMA_TUNNEL_URL, tun_ok, tun_msg, tun_ping)

    print(
        f"[{time.strftime('%H:%M:%S')}] Pushed to Kuma | "
        f"RAM: {ram_pct}% ({'UP' if ram_ok else 'DOWN'}) | "
        f"Disco: {disk_pct}% ({'UP' if disk_ok else 'DOWN'}) | "
        f"Bat: {bat_pct}% ({'UP' if bat_ok else 'DOWN'}) | "
        f"Tunnel: {'UP' if tun_ok else 'DOWN'} ({tun_ping}ms)",
        flush=True
    )


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        run_cycle()
        return

    print("[ResourceMonitor] Iniciando monitoramento contínuo para Uptime Kuma (35s)...", flush=True)
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[ResourceMonitor] Erro no ciclo de envio: {e}", flush=True)
        time.sleep(35)


if __name__ == "__main__":
    main()
