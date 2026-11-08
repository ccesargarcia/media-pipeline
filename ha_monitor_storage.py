#!/usr/bin/env python3
"""
Sensor de Espaço em Disco do Roteador para Home Assistant + Uptime Kuma Push.
Auto-instala smbprotocol se necessário no container do Home Assistant.
Gera saída JSON para o Home Assistant e envia heartbeat com métrica ao Uptime Kuma.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

try:
    import smbclient
except ImportError:
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "smbprotocol"], check=True)
        import smbclient
    except Exception as err:
        print(json.dumps({"error": f"smbprotocol ausente e falha ao instalar: {err}", "free_gb": 0}))
        sys.exit(1)

DEFAULT_PUSH_URL = "https://monitor.luisices.com.br/api/push/U7rbLdW2ijzLb9KksQ3afkxCtDUkXn7g"


def main():
    parser = argparse.ArgumentParser(description="Sensor de Espaço do Roteador para Home Assistant e Uptime Kuma")
    parser.add_argument("--host", default=os.environ.get("ROUTER_HOST", "192.168.0.1"), help="IP do roteador")
    parser.add_argument("--share", default=os.environ.get("ROUTER_SHARE", "G"), help="Share Samba")
    parser.add_argument("--user", default=os.environ.get("SMB_USER", os.environ.get("FTP_USER", "")), help="Usuário")
    parser.add_argument("--password", default=os.environ.get("SMB_PASSWORD", os.environ.get("FTP_PASSWORD", "")), help="Senha")
    parser.add_argument("--push-url", default=DEFAULT_PUSH_URL, help="URL Push Uptime Kuma")
    parser.add_argument("--min-gb", type=float, default=20.0, help="Limite crítico em GB")
    args = parser.parse_args()

    if not args.user:
        print(json.dumps({"error": "Usuario SMB/FTP nao configurado", "free_gb": 0, "status": "config_error"}))
        sys.exit(1)

    try:
        vol = smbclient.stat_volume(f"\\\\{args.host}\\{args.share}", username=args.user, password=args.password)
        total_gb = round(vol.total_size / (1024**3), 1)
        free_gb = round(vol.actual_available_size / (1024**3), 1)
        used_gb = round(total_gb - free_gb, 1)
        used_pct = round((used_gb / total_gb) * 100, 1) if total_gb > 0 else 0

        status = "up" if free_gb >= args.min_gb else "down"
        msg = f"OK: {free_gb}GB Livres ({100-used_pct:.1f}% de {total_gb}GB)" if status == "up" else f"ALERTA: Espaco Critico ({free_gb}GB)"

        # 1. Envia Push para Uptime Kuma
        try:
            base_url = args.push_url.split("?")[0]
            params = urllib.parse.urlencode({
                "status": status,
                "msg": msg,
                "ping": int(free_gb),
            })
            urllib.request.urlopen(f"{base_url}?{params}", timeout=8)
        except Exception:
            pass

        # 2. Retorna JSON completo para o Home Assistant
        output = {
            "free_gb": free_gb,
            "total_gb": total_gb,
            "used_gb": used_gb,
            "used_pct": used_pct,
            "status": status,
        }
        print(json.dumps(output))

    except Exception as e:
        # Notifica Uptime Kuma de queda se não conseguir falar com o roteador
        try:
            base_url = args.push_url.split("?")[0]
            params = urllib.parse.urlencode({
                "status": "down",
                "msg": f"Erro de conexao com HD: {str(e)[:60]}",
            })
            urllib.request.urlopen(f"{base_url}?{params}", timeout=5)
        except Exception:
            pass

        print(json.dumps({"error": str(e), "free_gb": 0, "status": "down"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
