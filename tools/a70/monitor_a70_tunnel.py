#!/usr/bin/env python3
"""
OCI Tunnel Monitor for Galaxy A70 (WireGuard / Tailscale)
Tests connectivity to wireguard.luisices.com.br (100.97.222.39) across all bridge ports
with built-in retry tolerance for transient power/network state transitions (e.g. AC disconnect).
"""

import socket
import time
import urllib.parse
import urllib.request
from ftplib import FTP

PUSH_TUNNEL_URL = "https://monitor.luisices.com.br/api/push/A70WireGuardTunnelPushToken2026X"
HOST = "wireguard.luisices.com.br"
EXPECTED_IP = "100.97.222.39"


def check_port(ip: str, port: int, timeout: float = 5.0, retries: int = 2):
    for attempt in range(retries):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((ip, port))
            s.close()
            return True, None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2.0)
            else:
                return False, e
    return False, "timeout"


def check_ftp(ip: str, timeout: float = 8.0, retries: int = 2):
    for attempt in range(retries):
        try:
            ftp = FTP()
            ftp.connect(ip, 2121, timeout=timeout)
            ftp.login("admin", "63274c0954")
            ftp.cwd("/G/Series/Longe demais - Segunda Temporada")
            ftp.quit()
            return True, None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2.0)
            else:
                return False, e
    return False, "timeout"


def check_from_cloud():
    try:
        ip = socket.gethostbyname(HOST)
        if ip != EXPECTED_IP:
            return False, f"DNS incorreto: {HOST} -> {ip}", 0
    except Exception as e:
        return False, f"Erro DNS {HOST}: {e}", 0

    t0 = time.time()
    ports = [(2222, "SSH"), (1080, "SOCKS5"), (2121, "FTP"), (5555, "ADB"), (8088, "BotWA")]
    for port, name in ports:
        ok, err = check_port(ip, port, timeout=5.0, retries=2)
        if not ok:
            return False, f"Tunel/Porta {port} ({name}) inacessivel da nuvem: {err}", 0

    ping_ms = max(1, int((time.time() - t0) * 1000 // len(ports)))

    ok_ftp, err_ftp = check_ftp(ip, timeout=8.0, retries=2)
    if not ok_ftp:
        return False, f"FTP via Tunel A70 ({ip}:2121) falhou: {err_ftp}", ping_ms

    return True, f"OK: Nuvem -> {HOST} ({ip}) | SSH:2222 SOCKS5:1080 FTP:2121 ADB:5555 BOT:8088", ping_ms


def push_kuma(ok: bool, msg: str, ping_ms: int):
    try:
        params = urllib.parse.urlencode({
            "status": "up" if ok else "down",
            "msg": msg,
            "ping": ping_ms,
        })
        req = urllib.request.Request(f"{PUSH_TUNNEL_URL}?{params}", headers={"User-Agent": "CloudTunnelMonitor/2.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as e:
        return f"Push error: {e}"


if __name__ == "__main__":
    while True:
        try:
            ok, msg, ping_ms = check_from_cloud()
            st = "up" if ok else "down"
            res = push_kuma(ok, msg, ping_ms)
            print(f"[TunnelMonitor] status={st} ({ping_ms}ms) {msg} -> {res}", flush=True)
        except Exception as e:
            print(f"[TunnelMonitor] erro: {e}", flush=True)
        time.sleep(45)
