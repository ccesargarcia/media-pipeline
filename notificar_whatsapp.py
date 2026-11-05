#!/usr/bin/env python3
"""
Envia notificações de status do pipeline de legendagem via WhatsApp (Evolution API).
Suporta envio silencioso (não falha o workflow se a notificação não puder ser entregue).
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def enviar_mensagem_whatsapp(
    texto: str,
    api_url: str = None,
    api_key: str = None,
    instance: str = None,
    destinatario: str = None,
    timeout: int = 15,
) -> bool:
    api_url = (api_url or os.environ.get("EVOLUTION_API_URL") or "https://wa.luisices.com.br").rstrip("/")
    api_key = api_key or os.environ.get("EVOLUTION_API_KEY")
    instance = instance or os.environ.get("EVOLUTION_INSTANCE") or "homeassistant"
    destinatario = destinatario or os.environ.get("WHATSAPP_RECIPIENT")

    if not api_key:
        print("[WhatsApp] Aviso: EVOLUTION_API_KEY não definida. Notificação ignorada.", file=sys.stderr)
        return False

    if not destinatario:
        print("[WhatsApp] Aviso: WHATSAPP_RECIPIENT não definido. Notificação ignorada.", file=sys.stderr)
        return False

    numero_limpo = "".join(filter(str.isdigit, destinatario))
    if not numero_limpo:
        print("[WhatsApp] Erro: Destinatário inválido.", file=sys.stderr)
        return False

    endpoint = f"{api_url}/message/sendText/{urllib.parse.quote(instance)}"
    payload = json.dumps({"number": numero_limpo, "text": texto.strip()}).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "apikey": api_key,
            "User-Agent": "MediaPipeline-Notifier/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status in (200, 201):
                sufixo = numero_limpo[-4:] if len(numero_limpo) >= 4 else "****"
                print(f"[WhatsApp] Notificação enviada com sucesso para o número terminado em {sufixo}.", flush=True)
                return True
            else:
                print(f"[WhatsApp] Resposta inesperada: HTTP {resp.status}", file=sys.stderr)
                return False
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")[:200]
        print(f"[WhatsApp] Falha HTTP {e.code} ao notificar: {err}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[WhatsApp] Falha de conexão ao notificar: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Envia notificação via Evolution API WhatsApp.")
    parser.add_argument("mensagem", help="Texto da notificação a ser enviada")
    parser.add_argument("--to", dest="recipient", help="Número do destinatário (com DDI e DDD)")
    parser.add_argument("--status", choices=["success", "warning", "error", "info"], default="info", help="Status para prefixo com emoji")
    parser.add_argument("--fail-on-error", action="store_true", help="Falha com exit code 1 se não enviar")
    args = parser.parse_args()

    emojis = {
        "success": "✅ *[Sucesso]*",
        "warning": "⚠️ *[Atenção]*",
        "error": "❌ *[Erro]*",
        "info": "🎬 *[Media Pipeline]*",
    }
    prefixo = emojis.get(args.status, "🎬")
    texto_completo = f"{prefixo}\n\n{args.mensagem}"

    sucesso = enviar_mensagem_whatsapp(
        texto=texto_completo,
        destinatario=args.recipient,
    )

    if not sucesso and args.fail_on_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
