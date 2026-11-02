#!/usr/bin/env python3
"""Traduz SRT usando um servidor local compatível com a API OpenAI."""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_URL = os.environ.get("LOCAL_LLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen3-8b-local")

SYSTEM_PROMPT = """Você é tradutor profissional de diálogos de séries turcas para português brasileiro.
Traduza com precisão, naturalidade e concisão, mantendo o tom e as relações entre personagens.

Contexto de Uzak Şehir: Alya é mãe de Deniz e esposa de Boran, que foi dado como morto e depois encontrado vivo em coma. Cihan lidera a família Albora; Sadakat é sua matriarca; Kaya é irmão de Cihan e noivo de İpek. A família rival é a Baybars.

Regras:
- O pronome turco "o" não indica gênero; deduza o gênero pelo contexto e evite inventar quando não houver informação suficiente.
- "Gelin" pode significar nora ou noiva. Use "nora" quando a fala vier da sogra ou da família do noivo; use "noiva" quando o próprio noivo falar.
- "Damat" pode significar genro ou noivo. Use a relação indicada pela cena.
- Adapte formas de tratamento e expressões culturais pelo contexto: "yenge", "abi", "abla", "ağa", "hanım", "başım üstüne", "Allah aşkına" e "geçmiş olsun".
- Se houver provável erro de reconhecimento de fala, use o contexto: "telsiz" pode ser rádio/comunicador; "Ali Hanım" ou "Hamada" pode referir-se a Alya; "Mardin" pode aparecer em nomes ou na canção de abertura. Não force essas correções quando a cena não sustentar a hipótese.
- Preserve cada ID como uma fala independente. Mantenha a ordem, não junte nem omita blocos, não acrescente explicações e preserve quebras de linha úteis.
- Use português brasileiro coloquial e legível para legendas. Não acrescente fatos ausentes do diálogo ou do contexto.

Responda somente com JSON no formato {"subtitles":[{"id":1,"text":"tradução"}]} e inclua exatamente todos os IDs recebidos."""


def parse_srt(content: str) -> list[dict]:
    items = []
    for block in re.split(r"\r?\n\s*\r?\n", content.strip()):
        lines = block.splitlines()
        if len(lines) >= 3 and "-->" in lines[1]:
            items.append({"idx": lines[0].strip(), "time": lines[1].strip(), "text": "\n".join(lines[2:]).strip()})
    return items


def request_batch(context: list[dict], batch: list[dict]) -> dict[int, str]:
    parts = []
    if context:
        parts.append("CONTEXTO ANTERIOR (somente referência; não traduza novamente):\n" + json.dumps(
            [{"id": x["id"], "original": x["text"], "pt_br": x.get("translation", "")} for x in context], ensure_ascii=False
        ))
    parts.append("Traduza estas falas:\n" + json.dumps(
        [{"id": x["id"], "text": x["text"]} for x in batch], ensure_ascii=False
    ))
    payload = {
        "model": MODEL,
        "temperature": 0.2,
        "max_tokens": 1536,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(parts) + "\n/no_think"},
        ],
    }
    req = urllib.request.Request(API_URL, data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=600) as response:
        data = json.loads(response.read().decode("utf-8"))
    text = data["choices"][0]["message"]["content"].strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
    result = json.loads(text)
    subtitles = result.get("subtitles") if isinstance(result, dict) else None
    if not isinstance(subtitles, list):
        raise ValueError("O servidor local não retornou a lista 'subtitles'.")
    translated = {}
    for row in subtitles:
        if not isinstance(row, dict) or "id" not in row or "text" not in row:
            raise ValueError("A resposta contém uma fala sem id ou texto.")
        key = int(row["id"])
        if key in translated:
            raise ValueError(f"A resposta repetiu o ID {key}.")
        translated[key] = str(row["text"]).strip()
    expected = {x["id"] for x in batch}
    if set(translated) != expected or any(not translated[i] for i in expected):
        raise ValueError("A resposta omitiu IDs, incluiu IDs inesperados ou retornou texto vazio.")
    return translated


def main() -> None:
    parser = argparse.ArgumentParser(description="Traduz SRT com modelo local via llama.cpp.")
    parser.add_argument("entrada")
    parser.add_argument("saida", nargs="?")
    parser.add_argument("-b", "--batch-size", type=int, default=8)
    parser.add_argument("--part-index", type=int, help="Índice da parte distribuída (começa em 0).")
    parser.add_argument("--parts", type=int, default=1, help="Número total de partes do arquivo.")
    parser.add_argument("--partial-json", action="store_true", help="Grava somente as traduções desta parte em JSON.")
    args = parser.parse_args()
    source = Path(args.entrada).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {source}")
    if args.batch_size <= 0:
        raise ValueError("O tamanho do lote precisa ser maior que zero.")
    if args.parts <= 0 or (args.part_index is not None and not 0 <= args.part_index < args.parts):
        raise ValueError("A parte precisa estar entre 0 e --parts - 1.")
    if args.partial_json and args.part_index is None:
        raise ValueError("--partial-json requer --part-index.")
    output = Path(args.saida).expanduser() if args.saida else source.with_name(f"{source.stem}.pt-BR.srt")
    raw = source.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    content = raw.decode("utf-16") if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else raw.decode("utf-8-sig", errors="replace")
    items = parse_srt(content)
    if not items:
        raise ValueError("Nenhuma fala SRT válida foi encontrada.")
    for i, item in enumerate(items, 1):
        item["id"] = i

    checkpoint = output.with_suffix(".ckpt.json")
    saved = {}
    if checkpoint.is_file():
        try:
            state = json.loads(checkpoint.read_text(encoding="utf-8"))
            if state.get("source_sha256") == source_hash:
                saved = {int(k): str(v) for k, v in state.get("translations", {}).items() if str(v).strip()}
        except (OSError, ValueError, TypeError):
            saved = {}
    for item in items:
        if item["id"] in saved:
            item["translation"] = saved[item["id"]]

    part_index = args.part_index or 0
    part_start = len(items) * part_index // args.parts
    part_end = len(items) * (part_index + 1) // args.parts
    for start in range(part_start, part_end, args.batch_size):
        batch = items[start:min(start + args.batch_size, part_end)]
        if all("translation" in item for item in batch):
            continue
        context = items[max(0, start - 4):start]
        print(f"Lote {start // args.batch_size + 1}/{(len(items) + args.batch_size - 1) // args.batch_size}: falas {start + 1}-{start + len(batch)}", flush=True)
        last_error = None
        for attempt in range(1, 4):
            try:
                translations = request_batch(context, batch)
                for item in batch:
                    item["translation"] = translations[item["id"]]
                saved.update(translations)
                checkpoint.parent.mkdir(parents=True, exist_ok=True)
                checkpoint.write_text(json.dumps({"source_sha256": source_hash, "translations": saved}, ensure_ascii=False), encoding="utf-8")
                break
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
                last_error = exc
                print(f"Tentativa {attempt}/3 falhou: {exc}", file=sys.stderr, flush=True)
                if attempt < 3:
                    time.sleep(attempt * 2)
        else:
            raise RuntimeError(f"Falha ao traduzir o lote {start // args.batch_size + 1}: {last_error}") from last_error

    output.parent.mkdir(parents=True, exist_ok=True)
    if args.partial_json:
        output.write_text(json.dumps({str(item["id"]): item["translation"] for item in items[part_start:part_end]}, ensure_ascii=False), encoding="utf-8")
        print(f"Parte local concluída: {output}", flush=True)
        return

    blocks = [f"{x['idx']}\n{x['time']}\n{x['translation']}" for x in items]
    output.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    checkpoint.unlink(missing_ok=True)
    print(f"Tradução local concluída: {output}", flush=True)


if __name__ == "__main__":
    main()
