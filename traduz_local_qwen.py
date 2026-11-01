#!/usr/bin/env python3
"""
Traduz arquivos .srt (Turco -> Português do Brasil) usando um servidor
llama.cpp / llama-server (OpenAI-compatible) rodando Qwen 2.5 Instruct
localmente ou no Google Cloud Run (Serverless).
100% sob seu controle, sem limites de requisição (HTTP 429).
Com barra de progresso visual, porcentagem exata, ETA e retomada por checkpoint.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_SERVER_URL = os.environ.get(
    "QWEN_SERVER_URL",
    "https://qwen-translator-wme7f6jafq-uc.a.run.app/v1",
)

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


def traduzir_lote_local(server_url: str, contexto_anterior: list, lote_atual: list) -> dict:
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
        "model": "qwen2.5",
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + "\nImportante: responda APENAS com o array JSON puro sem texto antes ou depois: [{\"id\": ..., \"text\": \"...\"}]"},
            {"role": "user", "content": "\n".join(prompt_partes)},
        ],
    }

    req = urllib.request.Request(
        f"{server_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=300) as resp:
        corpo = json.loads(resp.read().decode("utf-8"))

    conteudo_resp = corpo["choices"][0]["message"]["content"].strip()
    if conteudo_resp.startswith("```"):
        conteudo_resp = re.sub(r"^```(?:json)?\s*|\s*```$", "", conteudo_resp, flags=re.DOTALL).strip()

    lista = json.loads(conteudo_resp)
    if isinstance(lista, dict):
        lista = lista.get("subtitles") or lista.get("translations") or list(lista.values())[0]

    mapa = {}
    for obj in lista:
        if isinstance(obj, dict) and "id" in obj and "text" in obj:
            mapa[int(obj["id"])] = str(obj["text"]).strip()

    return mapa


def format_progress_bar(current: int, total: int, width: int = 25) -> str:
    filled = int(width * current / total) if total > 0 else 0
    return "=" * filled + ">" * (1 if filled < width else 0) + "." * max(0, width - filled - 1)


def main():
    parser = argparse.ArgumentParser(description="Traduz legenda .srt usando Qwen 2.5 (Cloud Run ou local).")
    parser.add_argument("entrada", help="Arquivo .srt de entrada")
    parser.add_argument("saida", nargs="?", help="Arquivo .srt de saída")
    parser.add_argument("-s", "--server-url", default=DEFAULT_SERVER_URL, help=f"URL da API OpenAI-compatível (padrão: {DEFAULT_SERVER_URL})")
    parser.add_argument("-b", "--batch-size", type=int, default=20, help="Falas por lote (padrão: 20)")
    args = parser.parse_args()

    entrada = Path(args.entrada).expanduser()
    if not entrada.is_file():
        print(f"Erro: Arquivo não encontrado: {entrada}", file=sys.stderr)
        sys.exit(1)

    saida = Path(args.saida).expanduser() if args.saida else entrada.with_name(f"{entrada.stem}.pt-BR.srt")

    dados = entrada.read_bytes()
    conteudo = dados.decode("utf-16") if dados.startswith((b"\xff\xfe", b"\xfe\xff")) else dados.decode("utf-8-sig", errors="replace")
    itens = parse_srt(conteudo)
    for i, item in enumerate(itens, start=1):
        item["id"] = i

    total_itens = len(itens)
    batch_size = args.batch_size
    total_lotes = (total_itens + batch_size - 1) // batch_size

    # Checkpoint para retomada resiliente
    ckpt_path = saida.with_suffix(".ckpt.json")
    traducoes = {}
    if ckpt_path.is_file():
        try:
            traducoes = {int(k): v for k, v in json.loads(ckpt_path.read_text(encoding="utf-8")).items()}
            print(f"==> Retomando progresso anterior: {len(traducoes)}/{total_itens} falas já traduzidas.", flush=True)
        except Exception:
            traducoes = {}

    for item in itens:
        if item["id"] in traducoes:
            item["traducao"] = traducoes[item["id"]]

    print("=" * 70, flush=True)
    print(f"==> Servidor Qwen: {args.server_url}", flush=True)
    print(f"==> Total de Falas: {total_itens} | Total de Lotes: {total_lotes} (Tamanho: {batch_size})", flush=True)
    print("=" * 70, flush=True)

    t_inicio = time.time()

    for idx_lote in range(total_lotes):
        inicio = idx_lote * batch_size
        fim = min(inicio + batch_size, total_itens)
        lote_atual = itens[inicio:fim]

        if all("traducao" in item for item in lote_atual):
            continue

        ctx_inicio = max(0, inicio - 6)
        contexto_anterior = itens[ctx_inicio:inicio]

        print(f"\n--> Processando Lote {idx_lote + 1}/{total_lotes} ({len(lote_atual)} falas: #{inicio + 1} a #{fim})...", flush=True)

        for tentativa in range(6):
            try:
                t_lote_start = time.time()
                mapa = traduzir_lote_local(args.server_url, contexto_anterior, lote_atual)
                t_lote_dur = time.time() - t_lote_start

                for item in lote_atual:
                    texto = mapa.get(item["id"], item["texto"])
                    item["traducao"] = texto
                    traducoes[item["id"]] = texto

                ckpt_path.write_text(json.dumps(traducoes, ensure_ascii=False), encoding="utf-8")

                # Cálculo de progresso, tempo e ETA
                tempo_decorrido = time.time() - t_inicio
                pct_concluido = (fim / total_itens) * 100
                velocidade = fim / tempo_decorrido if tempo_decorrido > 0 else 0
                falas_restantes = total_itens - fim
                tempo_restante = falas_restantes / velocidade if velocidade > 0 else 0

                el_m, el_s = divmod(int(tempo_decorrido), 60)
                eta_m, eta_s = divmod(int(tempo_restante), 60)
                bar = format_progress_bar(fim, total_itens, width=20)

                print(
                    f"✓ [{pct_concluido:5.1f}%] [{bar}] Lote {idx_lote + 1}/{total_lotes} OK ({t_lote_dur:.1f}s) | "
                    f"Concluídas: {fim}/{total_itens} | Tempo: {el_m:02d}:{el_s:02d} | ETA: {eta_m:02d}:{eta_s:02d} ({velocidade:.1f} falas/s)",
                    flush=True,
                )
                break
            except urllib.error.HTTPError as e:
                if e.code == 503 and tentativa < 5:
                    print(f"  [Cloud Run iniciando container / carregando modelo...]. Aguardando 15s...", file=sys.stderr, flush=True)
                    time.sleep(15)
                elif tentativa < 5:
                    espera = 5 * (tentativa + 1)
                    print(f"  [Tentativa {tentativa + 1}/6 HTTP {e.code}]. Nova tentativa em {espera}s...", file=sys.stderr, flush=True)
                    time.sleep(espera)
                else:
                    print(f"  [ERRO DEFINITIVO no lote {idx_lote + 1}]; mantendo falas originais.", file=sys.stderr, flush=True)
                    for item in lote_atual:
                        item["traducao"] = item["texto"]
            except Exception as e:
                if tentativa < 5:
                    espera = 4 * (tentativa + 1)
                    print(f"  [Tentativa {tentativa + 1}/6 falhou: {e}]. Tentando novamente em {espera}s...", file=sys.stderr, flush=True)
                    time.sleep(espera)
                else:
                    print(f"  [ERRO DEFINITIVO no lote {idx_lote + 1}]; mantendo falas originais.", file=sys.stderr, flush=True)
                    for item in lote_atual:
                        item["traducao"] = item["texto"]

    blocos_saida = []
    for item in itens:
        txt = item.get("traducao") or item["texto"]
        blocos_saida.append(f"{item['idx']}\n{item['tempo']}\n{txt}")

    tempo_total = time.time() - t_inicio
    tot_m, tot_s = divmod(int(tempo_total), 60)

    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text("\n\n".join(blocos_saida) + "\n", encoding="utf-8")
    print("=" * 70, flush=True)
    print(f"==> Concluído com sucesso via Qwen 2.5 em {tot_m:02d}m{tot_s:02d}s!", flush=True)
    print(f"==> Legenda salva em: {saida}", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
