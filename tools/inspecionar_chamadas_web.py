#!/usr/bin/env python3
"""Inspeciona as requisições de rede de uma página usando Chromium + Playwright.

Não captura corpos, cookies, cabeçalhos de autenticação nem valores de query string
por padrão. Os alvos UOL são destacados, mas todas as origens são resumidas.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


DEFAULT_TARGETS = ("api.security.uol.com.br", "dna.uol.com.br")


def safe_url(url: str, show_query: bool) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       parts.query if show_query else "", ""))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default="https://sac.uol.com.br/",
                        help="URL para abrir (padrão: https://sac.uol.com.br/)")
    parser.add_argument("--wait", type=float, default=12,
                        help="Segundos para observar requisições após carregar (padrão: 12)")
    parser.add_argument("--headed", action="store_true",
                        help="Abrir janela visível do Chromium")
    parser.add_argument("--executable-path",
                        help="Usar um Chromium instalado no sistema, em vez do navegador Playwright")
    parser.add_argument("--user-agent",
                        help="Definir um User-Agent explícito para a sessão do navegador")
    parser.add_argument("--interactive", action="store_true",
                        help="Com --headed, aguardar Enter para permitir interações manuais")
    parser.add_argument("--show-query", action="store_true",
                        help="Incluir query strings no relatório; podem conter dados sensíveis")
    parser.add_argument("--output", type=Path, default=Path("network-calls.json"),
                        help="Caminho do relatório JSON (padrão: network-calls.json)")
    parser.add_argument("--target", action="append", dest="targets",
                        help="Domínio para destacar; pode ser repetido")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright não está instalado. Execute: python -m pip install playwright",
              file=sys.stderr)
        return 2

    targets = tuple((args.targets or DEFAULT_TARGETS))
    calls: list[dict] = []
    request_rows: dict[int, dict] = {}
    websockets: list[dict] = []

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(
                headless=not args.headed,
                executable_path=args.executable_path,
            )
        except Exception as exc:
            print("Não foi possível iniciar Chromium. Instale-o com: "
                  "python -m playwright install chromium", file=sys.stderr)
            print(f"Detalhe: {exc}", file=sys.stderr)
            return 2

        context_options = {}
        if args.user_agent:
            context_options["user_agent"] = args.user_agent
        context = browser.new_context(**context_options)
        page = context.new_page()

        def on_request(request):
            row = {
                "time_utc": datetime.now(timezone.utc).isoformat(),
                "method": request.method,
                "url": safe_url(request.url, args.show_query),
                "host": urlsplit(request.url).hostname or "",
                "resource_type": request.resource_type,
                "status": None,
                "failure": None,
                "redirected_from": None,
            }
            if request.redirected_from:
                row["redirected_from"] = safe_url(request.redirected_from.url, args.show_query)
            calls.append(row)
            request_rows[id(request._impl_obj)] = row

        def on_response(response):
            row = request_rows.get(id(response.request._impl_obj))
            if row:
                row["status"] = response.status

        def on_request_failed(request):
            row = request_rows.get(id(request._impl_obj))
            if row:
                row["failure"] = request.failure or "request failed"

        page.on("request", on_request)
        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)
        page.on("websocket", lambda ws: websockets.append({
            "url": safe_url(ws.url, args.show_query),
            "host": urlsplit(ws.url).hostname or "",
        }))

        try:
            response = page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)
            if response:
                print(f"Página carregada: HTTP {response.status} {page.url}")
            else:
                print(f"Navegação concluída: {page.url}")
            if args.interactive:
                input("Interaja com a página no Chromium e pressione Enter para finalizar... ")
            elif args.wait > 0:
                time.sleep(args.wait)
        except Exception as exc:
            print(f"Aviso: navegação/interação terminou com erro: {exc}", file=sys.stderr)
        finally:
            browser.close()

    host_counts = Counter(row["host"] for row in calls)
    matched = [row for row in calls if any(
        row["host"] == target or row["host"].endswith("." + target)
        for target in targets
    )]
    report = {
        "page_url": safe_url(args.url, args.show_query),
        "final_page_url": safe_url(page.url, args.show_query),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "targets": list(targets),
        "request_count": len(calls),
        "domains": dict(sorted(host_counts.items())),
        "target_matches": matched,
        "websockets": websockets,
        "requests": calls,
        "query_strings_included": args.show_query,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")

    print(f"\nRequisições observadas: {len(calls)}")
    print("Domínios contatados:")
    for host, count in sorted(host_counts.items()):
        print(f"  {host}: {count}")
    print(f"\nCorrespondências para {', '.join(targets)}: {len(matched)}")
    for row in matched:
        status = row["status"] if row["status"] is not None else row["failure"] or "sem resposta"
        print(f"  {row['method']} {row['url']} [{status}; {row['resource_type']}]")
    print(f"\nRelatório completo: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
