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
TRANSLATION_CACHE_VERSION = "3"


class InvalidModelResponse(RuntimeError):
    """Resposta do servidor/modelo inutilizável; não deve ser repetida às cegas."""


SYSTEM_PROMPT = """Você é tradutor profissional de diálogos de séries turcas para português brasileiro.
Traduza com precisão, naturalidade e concisão, mantendo o tom e as relações entre personagens.

Contexto de Uzak Şehir: Alya é mãe de Deniz e esposa de Boran, que foi dado como morto e depois encontrado vivo em estado vegetativo e coma crítico. Não trate Boran como falecido depois dessa revelação. Cihan lidera a família Albora; Sadakat é sua matriarca; Kaya é irmão de Cihan e noivo de İpek. A família rival é a Baybars.

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
    if not content.strip():
        return items
    for block_number, block in enumerate(re.split(r"\r?\n\s*\r?\n", content.strip()), 1):
        lines = block.splitlines()
        if len(lines) < 3 or "-->" not in lines[1] or not lines[0].strip():
            raise ValueError(f"Bloco SRT inválido na posição {block_number}.")
        text = "\n".join(lines[2:]).strip()
        if not text:
            raise ValueError(f"Bloco SRT sem texto na posição {block_number}.")
        items.append({"idx": lines[0].strip(), "time": lines[1].strip(), "text": text})
    return items


def request_batch(context: list[dict], batch: list[dict]) -> dict[int, str]:
    is_translategemma = MODEL.startswith("translategemma")
    if is_translategemma:
        # TranslateGemma is a translation model, not a general JSON-following
        # chat model: send only source text and associate output with IDs here.
        translated = {}
        for item in batch:
            payload = {
                "model": MODEL,
                "temperature": 0,
                "max_tokens": 512,
                "messages": [{"role": "user", "content": item["text"]}],
                "chat_template_kwargs": {
                    "source_lang_code": "tr",
                    "target_lang_code": "pt-BR",
                },
            }
            req = urllib.request.Request(
                API_URL,
                data=json.dumps(payload, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=600) as response:
                response_body = response.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(response_body)
                choice = data["choices"][0]
                text = choice["message"]["content"].strip()
            except (json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError) as exc:
                excerpt = response_body[:500].replace("\n", "\\n") or "<resposta vazia>"
                raise InvalidModelResponse(
                    f"Resposta inválida do llama-server para a fala {item['id']}: {excerpt}"
                ) from exc
            if not text:
                if choice.get("finish_reason") == "length":
                    raise ValueError(f"TranslateGemma truncou a fala {item['id']} no limite de tokens.")
                raise InvalidModelResponse(
                    f"TranslateGemma retornou texto vazio para a fala {item['id']} "
                    f"(finish_reason={choice.get('finish_reason')!r})."
                )
            translated[item["id"]] = text
        return translated

    parts = []
    if context:
        parts.append("CONTEXTO ANTERIOR (somente referência; não traduza novamente):\n" + json.dumps(
            [{"id": x["id"], "original": x["text"], "pt_br": x.get("translation", "")} for x in context], ensure_ascii=False
        ))
    parts.append("Traduza estas falas:\n" + json.dumps(
        [{"id": x["id"], "text": x["text"]} for x in batch], ensure_ascii=False
    ))
    user_prompt = "\n\n".join(parts)
    payload = {
        "model": MODEL,
        "temperature": 0.2,
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt + ("\n/no_think" if "qwen" in MODEL.lower() else "")},
        ],
    }
    payload["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(API_URL, data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=600) as response:
        response_body = response.read().decode("utf-8", errors="replace")
    try:
        data = json.loads(response_body)
    except json.JSONDecodeError as exc:
        excerpt = response_body[:500].replace("\n", "\\n") or "<resposta vazia>"
        raise InvalidModelResponse(f"O servidor local retornou HTTP 200 sem JSON válido na resposta da API: {excerpt}") from exc
    try:
        choice = data["choices"][0]
        text = choice["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise InvalidModelResponse(f"Resposta da API sem choices[0].message.content: {str(data)[:500]}") from exc
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        # Alguns modelos acrescentam uma frase antes/depois do objeto, mesmo
        # quando o prompt pede somente JSON. Tenta recuperar o objeto completo.
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                result = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                excerpt = text[:500].replace("\n", "\\n") or "<conteúdo vazio>"
                if choice.get("finish_reason") == "length":
                    raise ValueError(f"Saída JSON truncada pelo limite de tokens: {excerpt}") from exc
                raise InvalidModelResponse(f"O modelo não retornou JSON válido; conteúdo recebido: {excerpt}") from exc
        else:
            excerpt = text[:500].replace("\n", "\\n") or "<conteúdo vazio>"
            if choice.get("finish_reason") == "length":
                raise ValueError(f"Saída truncada pelo limite de tokens: {excerpt}") from exc
            raise InvalidModelResponse(f"O modelo não retornou JSON; conteúdo recebido: {excerpt}") from exc
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


def translate_batch_with_fallbacks(context: list[dict], batch: list[dict]) -> dict[int, str]:
    """Tenta lotes menores quando a saída do modelo é inválida; nunca mascara falhas."""
    split_error = None
    last_error = None
    for attempt in range(1, 3):
        try:
            return request_batch(context, batch)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in (400, 413, 422):
                split_error = exc
                break
            split_error = None
            retryable = exc.code in (408, 425, 429) or 500 <= exc.code < 600
            if not retryable:
                raise RuntimeError(f"Erro HTTP não recuperável do servidor local: {exc.code} {exc.reason}") from exc
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = split_error = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            split_error = None
        if attempt < 2:
            print(f"Tentativa {attempt}/2 com lote de {len(batch)} falas falhou: {last_error}", file=sys.stderr, flush=True)
            time.sleep(attempt * 2)

    if split_error is None:
        raise RuntimeError(f"Falha temporária ao acessar o servidor local após 2 tentativas: {last_error}") from last_error

    # 2. Se o lote tem mais de 3 falas, subdivide na metade
    if len(batch) > 3:
        mid = len(batch) // 2
        print(f"Subdividindo lote de {len(batch)} falas em dois sublotes ({mid} e {len(batch) - mid}) para contornar o erro...", flush=True)
        part1 = batch[:mid]
        part2 = batch[mid:]
        res1 = translate_batch_with_fallbacks(context, part1)
        sub_context = list(context)
        for item in part1:
            sub_context.append({"id": item["id"], "text": item["text"], "translation": res1.get(item["id"], "")})
        res2 = translate_batch_with_fallbacks(sub_context[-4:], part2)
        return {**res1, **res2}

    # 3. Lote pequeno (<= 3 falas): traduz cada fala individualmente
    print(f"Processando {len(batch)} fala(s) individualmente para garantir integridade dos IDs...", flush=True)
    results = {}
    curr_context = list(context)
    for item in batch:
        item_id = item["id"]
        translated_text = None
        last_error = None
        for attempt in range(1, 4):
            try:
                single_res = request_batch(curr_context[-4:], [item])
                val = single_res.get(item_id, "").strip()
                if val:
                    translated_text = val
                    break
                last_error = ValueError("resposta vazia")
            except Exception as exc:
                last_error = exc
                print(f"Tentativa {attempt}/3 para fala individual {item_id} falhou: {exc}", file=sys.stderr, flush=True)
                time.sleep(attempt)

        if not translated_text:
            raise RuntimeError(f"Não foi possível traduzir a fala {item_id}; interrompendo para não publicar texto original como tradução: {last_error}") from last_error

        results[item_id] = translated_text
        curr_context.append({"id": item["id"], "text": item["text"], "translation": translated_text})

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Traduz SRT com modelo local via llama.cpp.")
    parser.add_argument("entrada")
    parser.add_argument("saida", nargs="?")
    parser.add_argument("-b", "--batch-size", type=int, default=12)
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
    translation_fingerprint = hashlib.sha256(
        f"{TRANSLATION_CACHE_VERSION}\0{MODEL}\0{args.batch_size}\0{SYSTEM_PROMPT}\0temperature=0.2;max_tokens=2048;json=v1;translategemma-plain-text-v1".encode("utf-8")
    ).hexdigest()
    saved = {}
    if checkpoint.is_file():
        try:
            state = json.loads(checkpoint.read_text(encoding="utf-8"))
            if state.get("source_sha256") == source_hash and state.get("translation_fingerprint") == translation_fingerprint:
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
        translations = translate_batch_with_fallbacks(context, batch)
        expected_ids = {item["id"] for item in batch}
        if set(translations) != expected_ids:
            raise RuntimeError(f"Lote incompleto: esperados={sorted(expected_ids)}, recebidos={sorted(translations)}")
        for item in batch:
            item["translation"] = translations[item["id"]]
        saved.update(translations)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_tmp = checkpoint.with_suffix(checkpoint.suffix + ".tmp")
        checkpoint_tmp.write_text(json.dumps({
            "source_sha256": source_hash,
            "translation_fingerprint": translation_fingerprint,
            "translations": saved,
        }, ensure_ascii=False), encoding="utf-8")
        checkpoint_tmp.replace(checkpoint)

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
