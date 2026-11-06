#!/usr/bin/env python3
"""
Monitora o espaço em disco do roteador TP-Link (via Samba porta 445)
e envia métricas em tempo real para o Uptime Kuma (Push Monitor).
"""
import argparse
import os
import sys
import urllib.parse
import urllib.request
import smbclient

DEFAULT_PUSH_URL = "https://monitor.luisices.com.br/api/push/U7rbLdW2ijzLb9KksQ3afkxCtDUkXn7g"


def monitorar_storage(
    host: str = "192.168.0.1",
    share: str = "G",
    user: str = "",
    password: str = "",
    push_url: str = DEFAULT_PUSH_URL,
    limite_critico_gb: float = 20.0,
) -> bool:
    user = user or os.environ.get("FTP_USER") or os.environ.get("SMB_USER", "")
    password = password or os.environ.get("FTP_PASSWORD") or os.environ.get("SMB_PASSWORD", "")

    if not user:
        print("[Monitor] Erro: Usuário do compartilhamento não configurado.", file=sys.stderr)
        return False

    try:
        vol = smbclient.stat_volume(
            f"\\\\{host}\\{share}",
            username=user,
            password=password,
        )
        total_gb = vol.total_size / (1024**3)
        free_gb = vol.actual_available_size / (1024**3)
        pct_livre = (free_gb / total_gb) * 100 if total_gb > 0 else 0

        # Define status de alerta se o espaço restante for menor que o limite configurado
        if free_gb < limite_critico_gb:
            status = "down"
            msg = f"⚠️ ALERTA: Espaço Crítico no HD! {free_gb:.1f}GB restantes ({pct_livre:.1f}% de {total_gb:.1f}GB)"
        else:
            status = "up"
            msg = f"OK: {free_gb:.1f}GB Livres ({pct_livre:.1f}% de {total_gb:.1f}GB)"

        ping = int(free_gb)
        print(f"[{status.upper()}] {msg} (Métrica/Ping: {ping} GB)", flush=True)

        base_url = push_url.split("?")[0]
        params = urllib.parse.urlencode({
            "status": status,
            "msg": msg,
            "ping": ping,
        })
        req = urllib.request.Request(f"{base_url}?{params}", headers={"User-Agent": "StorageMonitor/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"✅ Uptime Kuma atualizado: {resp.status} {resp.read().decode().strip()}", flush=True)
            return True

    except Exception as e:
        print(f"❌ [ERRO] Falha ao consultar disco em \\\\{host}\\{share}: {e}", file=sys.stderr)
        try:
            base_url = push_url.split("?")[0]
            params = urllib.parse.urlencode({
                "status": "down",
                "msg": f"Erro de conexão com o HD: {str(e)[:70]}",
            })
            urllib.request.urlopen(f"{base_url}?{params}", timeout=10)
        except Exception:
            pass
        return False


def main():
    parser = argparse.ArgumentParser(description="Envia status de disco do roteador ao Uptime Kuma")
    parser.add_argument("--host", default="192.168.0.1", help="Host do roteador")
    parser.add_argument("--share", default="G", help="Nome do compartilhamento")
    parser.add_argument("--user", default="", help="Usuário do compartilhamento")
    parser.add_argument("--password", default="", help="Senha do compartilhamento")
    parser.add_argument("--push-url", default=DEFAULT_PUSH_URL, help="URL de push do Uptime Kuma")
    parser.add_argument("--min-gb", type=float, default=20.0, help="Limite crítico em GB")
    args = parser.parse_args()

    ok = monitorar_storage(
        host=args.host,
        share=args.share,
        user=args.user,
        password=args.password,
        push_url=args.push_url,
        limite_critico_gb=args.min_gb,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
