#!/usr/bin/env python3
"""
Traduz arquivos .srt (Turco -> Português do Brasil) usando a Groq Cloud API
com o modelo openai/gpt-oss-120b (120B parâmetros) em alta velocidade e fidelidade dramática.
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

SYSTEM_PROMPT = """Você é um tradutor sênior de legendas de séries dramáticas turcas (dizis) para o Português do Brasil (PT-BR), especializado na série "Uzak Şehir" (Longe Demais), ambientada em Mardin.

PERSONAGENS E DINÂMICAS:
- Família Albora:
  * Cihan Albora: Líder patriarcal forte, protetor e honrado. Fala com autoridade e respeito.
  * Alya Albora: Médica pediatra canadense, mãe de Deniz e esposa de Boran. No início da história, vai a Mardin para o funeral do marido dado como morto. Firme, lúcida, elegante e corajosa.
  * Boran Albora: Marido de Alya, dado como morto e depois encontrado vivo em estado crítico, vegetativo e em coma. Após essa revelação, não o descreva como falecido; não antecipe a revelação em cenas anteriores.
  * Sadakat Albora (Sadakat Hanım): Matriarca implacável e tradicional. Chame de "Dona Sadakat" ou "Senhora Sadakat".
  * Kaya Albora: Irmão mais novo leal a Cihan, noivo de İpek.
  * İpek: Noiva de Kaya.
  * Şahin Albora: Primo impulsivo e explosivo (filho de Ecmel).
  * Deniz: Filho de Alya e Boran; ajuste a voz infantil à idade aparente e ao momento da história, sem fixar idade não confirmada.
  * Kadir, Muzaffer: Homens de confiança da mansão.
- Clã Baybars (Inimigos mortais):
  * Demir Baybars: Rival violento e implacável.
  * Ecmel: Traidor.

RELAÇÕES DE PARENTESCO E ARMADILHAS DO TURCO (MUITO IMPORTANTE):
- "Gelin" / "Gelinim":
  * Em turco significa tanto "noiva" quanto "NORA"!
  * Use "nora" quando a relação de sogra/família do noivo estiver confirmada; em outros casos, decida entre "nora" e "noiva" pelo contexto.
  * Se dita pelo próprio noivo, "noiva" pode ser adequado antes do casamento; considere a cena e o momento da trama.
- "Damat" / "Damadım":
  * Pode significar "genro" ou "noivo"; use a relação e a situação indicadas pela cena.
- "Anne diyeceksin bana": "Vai me chamar de mãe!" (a sogra tradicional turca exige que a nora a chame de mãe).

TRATAMENTOS CULTURAIS E VOCABULÁRIO:
- "Yenge" -> "Cunhada" (ou "Dona Alya" dependendo do respeito do capataz).
- "Abi" -> "Irmão" / "Meu irmão".
- "Abla" -> "Irmã".
- "Ağa" -> "Agha" ou "Patrão".
- "Konak / Konağın" -> "Mansão" / "Casa dos Albora".
- "Başım üstüne" -> "Às suas ordens" / "Com certeza".
- "Allah aşkına" -> "Pelo amor de Deus".
- "Geçmiş olsun" -> "Que passe logo" / "Melhoras".

CORREÇÃO DE ALUCINAÇÕES FONÉTICAS DO WHISPER NO TURCO:
- O áudio turco gravado com vento ou música tem erros fonéticos comuns:
  * "telsiz" pode referir-se a rádio/comunicador; confirme pela cena antes de corrigir uma transcrição incerta.
  * "Ali Hanım" pode ser uma referência a Alya; confirme pelo contexto. "Hamada" pode ser o personagem Hamada; não o confunda com Alya sem evidência.
  * Menções a Mardin podem ser nomes ou parte de uma canção; use o contexto.

REGRAS DE LEGENDA:
1. Português do Brasil coloquial dramático, sonoro e natural (como em dublagem/legendagem profissional de streaming).
2. Respeite pontuação de suspense, exclamações e quebras de frase.
3. Não resuma nem invente fatos fora do contexto; apenas traduza com exatidão e naturalidade.
4. Responda EXCLUSIVAMENTE em formato JSON com a chave "subtitles":
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


def traduzir_lote_groq(api_key: str, modelo: str, contexto_anterior: list, lote_atual: list):
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

    payload = {
        "model": modelo,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(prompt_partes)},
        ],
    }

    req = urllib.request.Request(
        GROQ_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "curl/8.5.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        headers = dict(resp.headers)
        corpo = json.loads(resp.read().decode("utf-8"))

    conteudo_resp = corpo["choices"][0]["message"]["content"].strip()
    
    # Limpa possíveis blocos ```json
    if conteudo_resp.startswith("```"):
        conteudo_resp = re.sub(r"^```(?:json)?\s*", "", conteudo_resp)
        conteudo_resp = re.sub(r"\s*```$", "", conteudo_resp)

    dado_json = json.loads(conteudo_resp, strict=False)

    if isinstance(dado_json, dict):
        lista = dado_json.get("subtitles") or dado_json.get("translations") or list(dado_json.values())[0]
    elif isinstance(dado_json, list):
        lista = dado_json
    else:
        raise ValueError(f"Formato inesperado retornado pela Groq: {conteudo_resp[:100]}")

    mapa = {}
    for obj in lista:
        if isinstance(obj, dict) and "id" in obj and "text" in obj:
            mapa[int(obj["id"])] = str(obj["text"]).strip()

    return mapa, headers


def main():
    parser = argparse.ArgumentParser(description="Traduz legenda .srt usando Groq Cloud API (openai/gpt-oss-120b).")
    parser.add_argument("entrada", help="Arquivo .srt de entrada")
    parser.add_argument("saida", nargs="?", help="Arquivo .srt de saída")
    parser.add_argument("-m", "--model", default="openai/gpt-oss-120b", help="Modelo Groq (padrão: openai/gpt-oss-120b)")
    parser.add_argument("-b", "--batch-size", type=int, default=30, help="Falas por lote (padrão: 30)")
    args = parser.parse_args()

    entrada = Path(args.entrada).expanduser()
    if not entrada.is_file():
        print(f"Erro: Arquivo não encontrado: {entrada}", file=sys.stderr)
        sys.exit(1)

    saida = Path(args.saida).expanduser() if args.saida else entrada.with_name(f"{entrada.stem}.pt-BR.srt")

    api_key = (
        os.environ.get("GROQ_API_KEY")
        or os.environ.get("GROK_API_KEY")
        or getpass.getpass("Cole sua chave Groq API (não aparecerá na tela): ")
    ).strip()

    if not api_key:
        print("Erro: Chave GROQ_API_KEY não encontrada.", file=sys.stderr)
        sys.exit(1)

    dados = entrada.read_bytes()
    conteudo = dados.decode("utf-16") if dados.startswith((b"\xff\xfe", b"\xfe\xff")) else dados.decode("utf-8-sig", errors="replace")
    itens = parse_srt(conteudo)
    for i, item in enumerate(itens, start=1):
        item["id"] = i

    print(f"==> Total de falas para traduzir via Groq ({args.model}): {len(itens)}", flush=True)

    batch_size = args.batch_size
    if batch_size <= 0:
        raise ValueError("O tamanho do lote precisa ser maior que zero.")
    total_lotes = (len(itens) + batch_size - 1) // batch_size
    traducoes = {}

    for idx_lote in range(total_lotes):
        inicio = idx_lote * batch_size
        fim = min(inicio + batch_size, len(itens))
        lote_atual = itens[inicio:fim]

        ctx_inicio = max(0, inicio - 5)
        contexto_anterior = itens[ctx_inicio:inicio]

        print(f"--> Processando Lote {idx_lote + 1}/{total_lotes} ({len(lote_atual)} falas: #{inicio + 1} a #{fim})...", flush=True)

        lote_concluido = False
        for tentativa in range(8):
            try:
                t0 = time.time()
                mapa, headers = traduzir_lote_groq(api_key, args.model, contexto_anterior, lote_atual)
                dt = time.time() - t0

                faltantes = [item["id"] for item in lote_atual if not mapa.get(item["id"])]
                if faltantes:
                    raise ValueError(f"A resposta omitiu {len(faltantes)} falas do lote.")

                # Verifica consumo de TPM (tokens por minuto)
                rem_tokens = int(headers.get("x-ratelimit-remaining-tokens", 99999))
                reset_str = headers.get("x-ratelimit-reset-tokens", "0s")
                if rem_tokens < 2200:
                    m = re.search(r"([\d\.]+)s", str(reset_str))
                    pausa = (float(m.group(1)) + 1.0) if m else 15.0
                    print(f"  [Groq TPM: restam {rem_tokens} tokens. Aguardando {pausa:.1f}s para renovação da janela...]", flush=True)
                    time.sleep(pausa)

                for item in lote_atual:
                    if item["id"] in mapa:
                        item["traducao"] = mapa[item["id"]]
                        traducoes[item["id"]] = mapa[item["id"]]
                print(f"  ✓ Lote {idx_lote + 1} traduzido com sucesso em {dt:.2f}s", flush=True)
                lote_concluido = True
                break
            except urllib.error.HTTPError as e:
                m = re.search(r"([\d\.]+)s", str(e.headers.get("x-ratelimit-reset-tokens", "")))
                espera = (float(m.group(1)) + 2.0) if m else (10.0 * (tentativa + 1))
                print(f"  [Groq HTTP {e.code}]. Aguardando {espera:.1f}s para liberação da cota...", file=sys.stderr, flush=True)
                time.sleep(espera)
            except Exception as e:
                espera = 4 * (tentativa + 1)
                print(f"  [Tentativa {tentativa + 1}/8 falhou: {e}]. Tentando em {espera}s...", file=sys.stderr, flush=True)
                time.sleep(espera)

        if not lote_concluido:
            raise RuntimeError(f"Falha ao traduzir o lote {idx_lote + 1} após 8 tentativas; nenhuma saída foi marcada como concluída.")

    blocos_saida = []
    for item in itens:
        t_final = traducoes.get(item["id"], item["texto"])
        blocos_saida.append(f"{item['idx']}\n{item['tempo']}\n{t_final}")

    saida.write_text("\n\n".join(blocos_saida) + "\n", encoding="utf-8")
    print(f"\n==> Tradução concluída com sucesso! Arquivo salvo em: {saida}")


if __name__ == "__main__":
    main()
