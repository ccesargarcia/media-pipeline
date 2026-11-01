#!/usr/bin/env python3
"""
Traduz arquivos .srt (ex: Turco -> Português do Brasil) usando a API do Google Gemini
com janela de contexto deslizante, autodetecção do modelo Flash mais recente ativo na conta,
rotação automática entre modelos Flash caso atinja cota gratuita (HTTP 429)
e retomada automática (checkpoint).
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

API_BASE = "https://generativelanguage.googleapis.com/v1beta"

SYSTEM_PROMPT = """Você é um tradutor profissional de legendas de cinema e séries dramáticas turcas (dizi), especializado em traduzir do Turco (TR) para o Português do Brasil (PT-BR).

Contexto da série (Uzak Şehir / Longe Demais - ambientada em Mardin):
- Personagens masculinos: Cihan (chefe da família Albora), Boran (irmão falecido de Cihan), Kaya (irmão mais novo de Cihan), Şahin (primo de Cihan), Demir (rival da família Baybars), Ecmel (pai de Şahin), Kadir, Muzaffer, Deniz (filho pequeno de Alya e Boran), Halis, Özkan.
- Personagens femininas: Alya (médica, viúva de Boran e mãe de Deniz), Sadakat (matriarca da família Albora, mãe de Cihan/Kaya/Nare), Nare (irmã de Cihan), Zerrin (filha de Ecmel, apaixonada por Kaya), Mine, Fidan (mãe de Şahin e Zerrin), Pakize.

Regras obrigatórias de tradução de legendas:
1. Preste muita atenção ao GÊNERO gramatical em português (masculino/feminino) observando quem fala e com quem fala pelo contexto das falas anteriores e seguintes (já que em turco "o" não tem gênero).
2. Conecte frases que começam em um bloco e continuam no bloco seguinte para que a leitura flua naturalmente.
3. Adapte expressões idiomáticas turcas ("Başım üstüne", "Geçmiş olsun", "Allah korusun", "Eline sağlık", "Ağa", "Hanım", "Abi", "Abla", "Yenge") para equivalentes naturais no Português do Brasil falado.
4. Mantenha o texto conciso para leitura confortável em tela.
5. Retorne EXCLUSIVAMENTE um array JSON válido no formato [{"id": <numero>, "text": "<tradução>"}] contendo exatamente os mesmos IDs solicitados no lote atual (NÃO inclua os itens de contexto anterior na resposta)."""


def listar_modelos_flash(api_key: str) -> list[str]:
    """Consulta a API do Gemini para descobrir os modelos Flash ativos na conta em ordem de preferência."""
    url = f"{API_BASE}/models?key={api_key}"
    req = urllib.request.Request(url, headers={"User-Agent": "Termux-SRT-Gemini/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"Erro ao validar chave Gemini (HTTP {e.code}): {detalhe}") from e

    disponiveis = []
    for m in data.get("models", []):
        metodos = m.get("supportedGenerationMethods", [])
        if "generateContent" not in metodos:
            continue
        nome = m.get("name", "").replace("models/", "")
        if any(x in nome for x in ("tts", "image", "vision", "embedding", "aqa", "bison", "learnlm")):
            continue
        disponiveis.append(nome)

    preferidos = [
        "gemini-3-flash-preview",
        "gemini-3.0-flash",
        "gemini-flash-latest",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-flash-lite-latest",
        "gemini-2.0-flash-lite",
    ]
    ordenados = [p for p in preferidos if p in disponiveis]
    for m in sorted(disponiveis, reverse=True):
        if "flash" in m and m not in ordenados:
            ordenados.append(m)

    if not ordenados and disponiveis:
        ordenados = disponiveis[:3]

    if not ordenados:
        raise RuntimeError("Nenhum modelo compatível com generateContent encontrado para esta chave.")
    return ordenados


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


def traduzir_lote(api_key: str, modelo: str, contexto_anterior: list, lote_atual: list) -> dict:
    prompt_partes = []
    if contexto_anterior:
        ctx_json = json.dumps(
            [{"id": item["id"], "tr": item["texto"], "pt": item.get("traducao", "")} for item in contexto_anterior],
            ensure_ascii=False,
        )
        prompt_partes.append(f"CONTEXTO ANTERIOR (apenas referência, NÃO inclua na saída):\n{ctx_json}\n")

    entrada_json = json.dumps(
        [{"id": item["id"], "text": item["texto"]} for item in lote_atual],
        ensure_ascii=False,
    )
    prompt_partes.append(
        f"TRADUZA ESTE LOTE ({len(lote_atual)} itens) PARA PORTUGUÊS DO BRASIL (PT-BR):\n{entrada_json}"
    )

    gen_config = {
        "temperature": 0.2,
        "responseMimeType": "application/json",
    }

    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": "\n".join(prompt_partes)}]}],
        "generationConfig": gen_config,
    }

    url = f"{API_BASE}/models/{modelo}:generateContent?key={api_key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Termux-SRT-Gemini/1.0"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=90) as resp:
        corpo = json.loads(resp.read().decode("utf-8"))

    candidatos = corpo.get("candidates", [])
    if not candidatos:
        raise RuntimeError(f"Resposta sem candidatos do Gemini: {corpo}")

    partes = candidatos[0].get("content", {}).get("parts", [])
    texto_resp = ""
    for p in partes:
        if "text" in p and not p.get("thought", False):
            texto_resp = p["text"].strip()
    if not texto_resp and partes:
        texto_resp = partes[-1].get("text", "").strip()

    if texto_resp.startswith("```"):
        texto_resp = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto_resp, flags=re.DOTALL).strip()

    lista_traduzida = json.loads(texto_resp)
    if not isinstance(lista_traduzida, list):
        raise ValueError("O modelo não retornou uma lista JSON.")

    mapa = {}
    for obj in lista_traduzida:
        if isinstance(obj, dict) and "id" in obj and "text" in obj:
            mapa[int(obj["id"])] = str(obj["text"]).strip()

    faltando = [item["id"] for item in lote_atual if item["id"] not in mapa]
    if len(faltando) > len(lote_atual) * 0.15:
        raise ValueError(f"O modelo omitiu {len(faltando)} itens do lote.")

    return mapa


def main():
    parser = argparse.ArgumentParser(description="Traduz legenda .srt usando Google Gemini com janela de contexto.")
    parser.add_argument("entrada", help="Arquivo .srt de entrada")
    parser.add_argument("saida", nargs="?", help="Arquivo .srt de saída (padrão: <entrada>.pt-BR.srt)")
    parser.add_argument("-m", "--model", default="auto", help="Modelo Gemini (padrão: auto - detecta o Flash mais novo)")
    parser.add_argument("-b", "--batch-size", type=int, default=80, help="Falas por lote (padrão: 80)")
    args = parser.parse_args()

    entrada = Path(args.entrada).expanduser()
    if not entrada.is_file():
        print(f"Erro: Arquivo não encontrado: {entrada}", file=sys.stderr)
        sys.exit(1)

    if args.saida:
        saida = Path(args.saida).expanduser()
    else:
        saida = entrada.with_name(f"{entrada.stem}.pt-BR.srt")

    api_key = (
        os.environ.get("GEMINI_TRANSLATE_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or getpass.getpass("Cole sua GEMINI_TRANSLATE_KEY (não aparecerá na tela): ")
    )
    api_key = api_key.strip()
    if not api_key:
        print("Erro: É necessária uma GEMINI_TRANSLATE_KEY (obtenha em https://aistudio.google.com/apikey).", file=sys.stderr)
        sys.exit(1)

    if args.model == "auto":
        print("==> Consultando modelos disponíveis na sua conta Gemini...", flush=True)
        modelos_disponiveis = listar_modelos_flash(api_key)
    else:
        modelos_disponiveis = [args.model]

    idx_modelo = 0
    modelo = modelos_disponiveis[idx_modelo]
    print(f"==> Modelo principal selecionado: {modelo} (alternativas de fallback: {modelos_disponiveis[1:4]})", flush=True)

    dados = entrada.read_bytes()
    conteudo = dados.decode("utf-16") if dados.startswith((b"\xff\xfe", b"\xfe\xff")) else dados.decode("utf-8-sig", errors="replace")
    itens = parse_srt(conteudo)
    for i, item in enumerate(itens, start=1):
        item["id"] = i

    print(f"==> Total de falas para traduzir: {len(itens)}", flush=True)

    ckpt_path = saida.with_suffix(".ckpt.json")
    traducoes_salvas = {}
    if ckpt_path.is_file():
        try:
            traducoes_salvas = {int(k): v for k, v in json.loads(ckpt_path.read_text(encoding="utf-8")).items()}
            print(f"==> Retomando progresso anterior: {len(traducoes_salvas)}/{len(itens)} falas já traduzidas.", flush=True)
        except Exception:
            traducoes_salvas = {}

    for item in itens:
        if item["id"] in traducoes_salvas:
            item["traducao"] = traducoes_salvas[item["id"]]

    batch_size = args.batch_size
    total_lotes = (len(itens) + batch_size - 1) // batch_size

    for idx_lote in range(total_lotes):
        inicio = idx_lote * batch_size
        fim = min(inicio + batch_size, len(itens))
        lote_atual = itens[inicio:fim]

        if all("traducao" in item for item in lote_atual):
            continue

        ctx_inicio = max(0, inicio - 8)
        contexto_anterior = itens[ctx_inicio:inicio]

        for tentativa in range(6):
            try:
                mapa = traduzir_lote(api_key, modelo, contexto_anterior, lote_atual)
                for item in lote_atual:
                    texto_trad = mapa.get(item["id"], item["texto"])
                    item["traducao"] = texto_trad
                    traducoes_salvas[item["id"]] = texto_trad
                ckpt_path.write_text(json.dumps(traducoes_salvas, ensure_ascii=False), encoding="utf-8")
                print(f"[{idx_lote + 1}/{total_lotes}] Traduzidas {fim}/{len(itens)} falas ({modelo})...", flush=True)
                break
            except urllib.error.HTTPError as e:
                detalhe = e.read().decode("utf-8", "replace")[:300]
                if e.code == 429 and len(modelos_disponiveis) > 1 and tentativa in (1, 3):
                    idx_modelo = (idx_modelo + 1) % len(modelos_disponiveis)
                    modelo = modelos_disponiveis[idx_modelo]
                    print(f"Cota atingida no modelo anterior (HTTP 429). Alternando automaticamente para: {modelo}", file=sys.stderr, flush=True)
                    time.sleep(3)
                elif e.code == 429 and tentativa < 5:
                    espera = 15 * (tentativa + 1)
                    print(f"Limite de requisições (HTTP 429). Aguardando {espera}s...", file=sys.stderr, flush=True)
                    time.sleep(espera)
                elif tentativa < 5:
                    espera = 8 * (tentativa + 1)
                    print(f"Erro HTTP {e.code} no lote {idx_lote + 1}. Nova tentativa em {espera}s...", file=sys.stderr, flush=True)
                    time.sleep(espera)
                else:
                    print(f"Falha no lote {idx_lote + 1} após tentativas; mantendo original.", file=sys.stderr, flush=True)
            except Exception as e:
                if tentativa < 5:
                    espera = 6 * (tentativa + 1)
                    print(f"Aviso no lote {idx_lote + 1} ({e}). Tentando novamente em {espera}s...", file=sys.stderr, flush=True)
                    time.sleep(espera)
                else:
                    print(f"Falha no lote {idx_lote + 1} ({e}); mantendo original.", file=sys.stderr, flush=True)

        if idx_lote + 1 < total_lotes:
            time.sleep(1.5)

    blocos_saida = []
    for item in itens:
        texto_final = item.get("traducao") or item["texto"]
        blocos_saida.append(f"{item['idx']}\n{item['tempo']}\n{texto_final}")

    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text("\n\n".join(blocos_saida) + "\n", encoding="utf-8")
    if ckpt_path.is_file() and len(traducoes_salvas) >= len(itens):
        ckpt_path.unlink()
    print(f"==> Concluído! ({len(traducoes_salvas)}/{len(itens)} traduzidas) Legenda salva em: {saida}", flush=True)


if __name__ == "__main__":
    main()
