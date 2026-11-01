#!/usr/bin/env python3
"""
Traduz arquivos .srt (Turco -> Português do Brasil) usando a API da Groq Cloud
(modelo Llama 3.3 70B Versatile) com janela de contexto deslizante e alta velocidade.
"""
import argparse
import getpass
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """Você é um tradutor profissional de legendas de cinema e séries dramáticas turcas (dizi), especializado em traduzir do Turco (TR) para o Português do Brasil (PT-BR).

Contexto da série (Uzak Şehir / Longe Demais - ambientada em Mardin):
- Personagens masculinos: Cihan (chefe da família Albora), Boran (irmão que reapareceu), Kaya (irmão mais novo), Şahin (primo), Demir (rival Baybars), Ecmel (pai de Şahin), Kadir, Muzaffer, Deniz (filho pequeno de Alya), Halis, Özkan.
- Personagens femininas: Alya (médica, mãe de Deniz), Sadakat (matriarca dos Albora), Nare, Zerrin, Mine, Fidan, Pakize, Ümmü Hanım.

Regras obrigatórias de tradução de legendas:
1. Gênero gramatical: determine masculino/feminino pelo contexto de quem fala e de quem se fala (em turco "o" é neutro).
2. Conecte falas que foram quebradas entre blocos para que a leitura flua naturalmente.
3. Adapte expressões idiomáticas ("Yenge" -> "Cunhada", "Abi" -> "Irmão", "Abla" -> "Irmã", "Ağa", "Hanım", "Geçmiş olsun", "Başım üstüne") para o português brasileiro falado.
4. Mantenha o texto conciso para leitura em tela.
5. Retorne EXCLUSIVAMENTE um array JSON válido no formato: [{"id": <numero>, "text": "<tradução>"}] contendo todos os IDs solicitados."""


def parse_srt(conteudo: str):
    blocos = re.split(r"\r?\n\s*\r?\n", conteudo.strip())
    itens = []
    for bloco in blocos:
        linhas = [l.rstrip("\r") for l in bloco.splitlines()]
        if len(linhas) >= 3 and "-->" in linhas[1]:
            itens.append({
                "idx": linhas[0].strip(),
                "tempo": linhas[1].strip(),
                "texto": "\n".join(linhas[2:]).strip(),
            })
    return itens


def traduzir_lote_groq(api_key: str, modelo: str, contexto_anterior: list, lote_atual: list) -> dict:
    prompt_partes = []
    if contexto_anterior:
        ctx_json = json.dumps(
            [{"id": item["id"], "tr": item["texto"], "pt": item.get("traducao", "")} for item in contexto_anterior],
            ensure_ascii=False,
        )
        prompt_partes.append(f"CONTEXTO ANTERIOR (referência):\n{ctx_json}\n")

    entrada_json = json.dumps(
        [{"id": item["id"], "text": item["texto"]} for item in lote_atual],
        ensure_ascii=False,
    )
    prompt_partes.append(
        f"TRADUZA ESTE LOTE ({len(lote_atual)} itens) PARA PORTUGUÊS DO BRASIL (PT-BR):\n{entrada_json}"
    )

    payload = {
        "model": modelo,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + "\nRetorne um objeto JSON contendo a chave 'subtitles' com a lista: {\"subtitles\": [{\"id\": ..., \"text\": ...}]}"},
            {"role": "user", "content": "\n".join(prompt_partes)},
        ],
    }

    req = urllib.request.Request(
        GROQ_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Termux-SRT-Groq/1.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        corpo = json.loads(resp.read().decode("utf-8"))

    conteudo_resp = corpo["choices"][0]["message"]["content"].strip()
    dado_json = json.loads(conteudo_resp)
    
    if isinstance(dado_json, dict):
        lista = dado_json.get("subtitles") or dado_json.get("translations") or list(dado_json.values())[0]
    elif isinstance(dado_json, list):
        lista = dado_json
    else:
        raise ValueError("Resposta inesperada da Groq.")

    mapa = {}
    for obj in lista:
        if isinstance(obj, dict) and "id" in obj and "text" in obj:
            mapa[int(obj["id"])] = str(obj["text"]).strip()

    return mapa


def main():
    parser = argparse.ArgumentParser(description="Traduz legenda .srt usando Groq Cloud API (Llama 3.3 70B).")
    parser.add_argument("entrada", help="Arquivo .srt de entrada")
    parser.add_argument("saida", nargs="?", help="Arquivo .srt de saída")
    parser.add_argument("-m", "--model", default="llama-3.3-70b-versatile", help="Modelo Groq")
    parser.add_argument("-b", "--batch-size", type=int, default=50, help="Falas por lote (padrão: 50)")
    args = parser.parse_args()

    entrada = Path(args.entrada).expanduser()
    if not entrada.is_file():
        print(f"Erro: Arquivo não encontrado: {entrada}", file=sys.stderr)
        sys.exit(1)

    saida = Path(args.saida).expanduser() if args.saida else entrada.with_name(f"{entrada.stem}.pt-BR.srt")

    api_key = (
        os.environ.get("GROQ_API_KEY")
        or os.environ.get("GROK_API_KEY")
        or getpass.getpass("Cole sua chave Groq/Grok API (não aparecerá na tela): ")
    ).strip()

    if not api_key:
        print("Erro: Chave da API necessária.", file=sys.stderr)
        sys.exit(1)

    dados = entrada.read_bytes()
    conteudo = dados.decode("utf-16") if dados.startswith((b"\xff\xfe", b"\xfe\xff")) else dados.decode("utf-8-sig", errors="replace")
    itens = parse_srt(conteudo)
    for i, item in enumerate(itens, start=1):
        item["id"] = i

    print(f"==> Total de falas para traduzir via Groq ({args.model}): {len(itens)}", flush=True)

    batch_size = args.batch_size
    total_lotes = (len(itens) + batch_size - 1) // batch_size
    traducoes = {}

    for idx_lote in range(total_lotes):
        inicio = idx_lote * batch_size
        fim = min(inicio + batch_size, len(itens))
        lote_atual = itens[inicio:fim]

        ctx_inicio = max(0, inicio - 6)
        contexto_anterior = itens[ctx_inicio:inicio]

        for tentativa in range(4):
            try:
                mapa = traduzir_lote_groq(api_key, args.model, contexto_anterior, lote_atual)
                for item in lote_atual:
                    texto = mapa.get(item["id"], item["texto"])
                    item["traducao"] = texto
                    traducoes[item["id"]] = texto
                print(f"[{idx_lote + 1}/{total_lotes}] Traduzidas {fim}/{len(itens)} falas...", flush=True)
                break
            except Exception as e:
                if tentativa < 3:
                    espera = 5 * (tentativa + 1)
                    print(f"Aviso no lote {idx_lote + 1} ({e}). Tentando novamente em {espera}s...", file=sys.stderr, flush=True)
                    time.sleep(espera)
                else:
                    print(f"Falha no lote {idx_lote + 1}; mantendo original.", file=sys.stderr, flush=True)
                    for item in lote_atual:
                        item["traducao"] = item["texto"]

        time.sleep(0.5)

    blocos_saida = []
    for item in itens:
        txt = item.get("traducao") or item["texto"]
        blocos_saida.append(f"{item['idx']}\n{item['tempo']}\n{txt}")

    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text("\n\n".join(blocos_saida) + "\n", encoding="utf-8")
    print(f"==> Concluído via Groq! Legenda salva em: {saida}", flush=True)


if __name__ == "__main__":
    main()
