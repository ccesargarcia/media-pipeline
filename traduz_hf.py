#!/usr/bin/env python3
"""
Traduz arquivos .srt (Turco -> Português do Brasil) usando a API oficial do Hugging Face
com o modelo meta-llama/Llama-3.3-70B-Instruct em alta velocidade e fidelidade dramática.
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

HF_ROUTER_URL = "https://router.huggingface.co/hf-inference/models/meta-llama/Llama-3.3-70B-Instruct/v1/chat/completions"
DEFAULT_MODEL = "meta-llama/Llama-3.3-70B-Instruct"

SYSTEM_PROMPT = """Você é um tradutor sênior de legendas de séries dramáticas turcas (dizis) para o Português do Brasil (PT-BR), especializado na série "Uzak Şehir" (Longe Demais), ambientada em Mardin.

PERSONAGENS E DINÂMICAS:
- Família Albora:
  * Cihan Albora: Líder patriarcal forte, protetor e honrado. Fala com autoridade e respeito.
  * Alya Albora: Médica pediatra canadense, mãe de Deniz e esposa de Boran. Firme, lúcida, elegante e corajosa.
  * Boran Albora: Marido de Alya, dado como morto e depois encontrado vivo em estado crítico/vegetativo.
  * Sadakat Albora (Sadakat Hanım): Matriarca implacável e tradicional. Chame de "Dona Sadakat". Pronomes femininos SEMPRE (ela, dela, a senhora).
  * Kaya Albora: Irmão mais novo leal a Cihan, noivo de İpek.
  * İpek: Noiva de Kaya e futura nora de Sadakat.
  * Şahin Albora: Primo impulsivo (filho de Ecmel e Fidan).
  * Nare Albora: Irmã mais nova de Cihan, grávida em segredo.
  * Deniz: Filho pequeno de Alya e Boran (fala como criança de 5-6 anos).
  * Zerrin: Filha de Ecmel e Fidan, sequestrada. Sempre feminino (ela, dela).
- Clã Baybars:
  * Demir Baybars: Arqui-inimigo da família Albora.
  * Ecmel Albora: Tio conspirador.

RELAÇÕES DE PARENTESCO E ARMADILHAS DO TURCO:
- "Gelin" / "Gelinim": "Nora" / "Minha nora" quando dita pela sogra ou família do noivo; "Noiva" se dita pelo noivo.
- "Damat" / "Damadım": "Genro" / "Nosso genro" pelos sogros; "Noivo" pela noiva.
- "Anne diyeceksin bana": "Vai me chamar de mãe!"
- "Abla" -> "Irmã" / "Tia" | "Abi" -> "Irmão" | "Ağa" -> "Agha" ou "Patrão"
- "Başım üstüne" -> "Às suas ordens" / "Com certeza"
- "Allah aşkına" -> "Pelo amor de Deus" | "Geçmiş olsun" -> "Melhoras"
- "Konak" -> "Mansão"

REGRAS OBRIGATÓRIAS DE LEGENDA:
1. Português do Brasil coloquial dramático, sonoro e natural (estilo dublagem/legendagem de streaming).
2. Não omita nem resuma falas. Cada fala turca deve ter exatamente uma fala traduzida correspondente com o mesmo ID (paridade 1:1 rigorosa).
3. Responda EXCLUSIVAMENTE em formato JSON com a chave "subtitles":
   {"subtitles": [{"id": <int>, "text": "<tradução em PT-BR>"}]}"""


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


def traduzir_lote_hf(api_key: str, modelo: str, contexto_anterior: list, lote_atual: list):
    prompt_partes = []
    if contexto_anterior:
        ctx_json = json.dumps(
            [{"id": item["id"], "tr": item["texto"], "pt": item.get("traducao", "")} for item in contexto_anterior],
            ensure_ascii=False,
        )
        prompt_partes.append(f"CONTEXTO ANTERIOR (para continuidade da cena):\n{ctx_json}\n")

    entrada_json = json.dumps(
        [{"id": item["id"], "text": item["texto"]} for item in lote_atual],
        ensure_ascii=False,
    )
    prompt_partes.append(
        f"TRADUZA ESTE LOTE DE FALA ({len(lote_atual)} itens) PARA PORTUGUÊS DO BRASIL (PT-BR):\n{entrada_json}"
    )

    url = f"https://router.huggingface.co/hf-inference/models/{modelo}/v1/chat/completions"

    payload = {
        "model": modelo,
        "temperature": 0.2,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(prompt_partes)},
        ],
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "MediaPipeline-HF/1.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=90) as resp:
        headers = dict(resp.headers)
        corpo = json.loads(resp.read().decode("utf-8"))

    conteudo_resp = corpo["choices"][0]["message"]["content"].strip()
    if conteudo_resp.startswith("```"):
        conteudo_resp = re.sub(r"^```(?:json)?\s*", "", conteudo_resp)
        conteudo_resp = re.sub(r"\s*```$", "", conteudo_resp)

    dado_json = json.loads(conteudo_resp, strict=False)
    if isinstance(dado_json, dict):
        lista = dado_json.get("subtitles") or dado_json.get("translations") or list(dado_json.values())[0]
    elif isinstance(dado_json, list):
        lista = dado_json
    else:
        raise ValueError(f"Formato inesperado retornado pelo Hugging Face: {conteudo_resp[:100]}")

    mapa = {}
    for obj in lista:
        if isinstance(obj, dict) and "id" in obj and "text" in obj:
            mapa[int(obj["id"])] = str(obj["text"]).strip()

    return mapa, headers


def main():
    parser = argparse.ArgumentParser(description="Traduz legenda .srt usando Llama-3.3-70B-Instruct no Hugging Face.")
    parser.add_argument("entrada", help="Arquivo .srt de entrada")
    parser.add_argument("saida", nargs="?", help="Arquivo .srt de saída")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, help=f"Modelo HF (padrão: {DEFAULT_MODEL})")
    parser.add_argument("-b", "--batch-size", type=int, default=35, help="Falas por lote (padrão: 35)")
    args = parser.parse_args()

    entrada = Path(args.entrada).expanduser()
    if not entrada.is_file():
        print(f"Erro: Arquivo não encontrado: {entrada}", file=sys.stderr)
        sys.exit(1)

    saida = Path(args.saida).expanduser() if args.saida else entrada.with_name(f"{entrada.stem}.pt-BR.srt")

    api_key = (
        os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        or getpass.getpass("Cole seu Hugging Face Token (HF_TOKEN): ")
    ).strip()

    if not api_key:
        print("Erro: HF_TOKEN não encontrado.", file=sys.stderr)
        sys.exit(1)

    dados = entrada.read_bytes()
    conteudo = dados.decode("utf-16") if dados.startswith((b"\xff\xfe", b"\xfe\xff")) else dados.decode("utf-8-sig", errors="replace")
    itens = parse_srt(conteudo)
    for i, item in enumerate(itens, start=1):
        item["id"] = i

    print(f"==> Total de falas para traduzir via Hugging Face ({args.model}): {len(itens)}", flush=True)

    batch_size = args.batch_size
    total_lotes = (len(itens) + batch_size - 1) // batch_size
    traducoes = {}

    for idx_lote in range(total_lotes):
        inicio = idx_lote * batch_size
        fim = min(inicio + batch_size, len(itens))
        lote_atual = itens[inicio:fim]

        ctx_inicio = max(0, inicio - 6)
        contexto_anterior = itens[ctx_inicio:inicio]

        print(f"--> Processando Lote {idx_lote + 1}/{total_lotes} ({len(lote_atual)} falas: #{inicio + 1} a #{fim})...", flush=True)

        for tentativa in range(8):
            try:
                t0 = time.time()
                mapa, headers = traduzir_lote_hf(api_key, args.model, contexto_anterior, lote_atual)
                dt = time.time() - t0

                faltantes = [item["id"] for item in lote_atual if not mapa.get(item["id"])]
                if faltantes:
                    raise ValueError(f"A resposta omitiu {len(faltantes)} falas do lote.")

                for item in lote_atual:
                    if item["id"] in mapa:
                        item["traducao"] = mapa[item["id"]]
                        traducoes[item["id"]] = mapa[item["id"]]
                print(f"  ✓ Lote {idx_lote + 1} traduzido com sucesso em {dt:.2f}s", flush=True)
                break
            except urllib.error.HTTPError as e:
                espera = 15.0 * (tentativa + 1)
                print(f"  [HF HTTP {e.code}]. Aguardando {espera:.1f}s...", file=sys.stderr, flush=True)
                time.sleep(espera)
            except Exception as e:
                espera = 8.0 * (tentativa + 1)
                print(f"  [Aviso lote {idx_lote + 1}: {e}]. Tentando novamente em {espera:.1f}s...", file=sys.stderr, flush=True)
                time.sleep(espera)

        time.sleep(1.0)

    blocos_saida = []
    for item in itens:
        texto_final = item.get("traducao") or item["texto"]
        blocos_saida.append(f"{item['idx']}\n{item['tempo']}\n{texto_final}")

    saida.write_text("\n\n".join(blocos_saida) + "\n", encoding="utf-8")
    print(f"\n✅ Tradução concluída com sucesso! Arquivo salvo em: {saida}")


if __name__ == "__main__":
    main()
