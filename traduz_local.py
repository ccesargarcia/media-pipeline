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
import urllib.parse
from pathlib import Path

API_URL = os.environ.get("LOCAL_LLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen3-8b-local")
TRANSLATION_CACHE_VERSION = "5"
CONTEXT_WINDOW_SIZE = 8


class LocalServerConfigurationError(RuntimeError):
    """Falha permanente do servidor; repetir cada fala não resolve."""


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
- Se houver provável erro de reconhecimento de fala, use o contexto: "telsiz" pode ser rádio/comunicador; "Ali Hanım" pode referir-se a Alya; "Hamada" é o personagem assassinado no passado (não confunda com Alya); "Mardin" pode aparecer em nomes ou na canção de abertura. Não force essas correções quando a cena não sustentar a hipótese.
- Preserve cada ID como uma fala independente. Mantenha a ordem, não junte nem omita blocos, não acrescente explicações e preserve quebras de linha úteis.
- Use português brasileiro coloquial e legível para legendas. Não acrescente fatos ausentes do diálogo ou do contexto.

Responda somente com JSON no formato {"subtitles":[{"id":1,"text":"tradução"}]} e inclua exatamente todos os IDs recebidos."""


def carregar_prompt_sistema(base_prompt: str) -> str:
    """Carrega as diretrizes de personagens e tradução da skill dizi-translator se o arquivo existir."""
    skill_paths = [
        Path(__file__).resolve().parent / ".agents/skills/dizi-translator/SKILL.md",
        Path.home() / ".agents/skills/dizi-translator/SKILL.md",
    ]
    for sp in skill_paths:
        if sp.is_file():
            try:
                conteudo = sp.read_text(encoding="utf-8")
                conteudo = re.sub(r"^---\s*\n.*?\n---\s*\n", "", conteudo, flags=re.DOTALL).strip()
                match = re.search(r"##\s*3\.", conteudo)
                if match:
                    conteudo = conteudo[:match.start()].strip()
                print(f"==> Diretrizes de tradução da skill dizi-translator incorporadas a partir de: {sp}", flush=True)
                return f"{base_prompt}\n\n--- DIRETRIZES DA SÉRIE E REGRAS DE TRADUÇÃO ---\n{conteudo}"
            except Exception as e:
                print(f"Aviso ao carregar skill ({sp}): {e}", file=sys.stderr)
    return base_prompt

PROMPT_SISTEMA_COMPLETO = carregar_prompt_sistema(SYSTEM_PROMPT)


def parse_json_from_text(raw_text: str):
    """Extrai e decodifica JSON de texto puro, blocos markdown ou preâmbulos/posfácios."""
    raw_text = raw_text.strip()
    try:
        return json.loads(raw_text)
    except Exception:
        pass

    # Tenta blocos com cercas markdown (```json ... ``` ou ``` ... ```)
    fences = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text)
    for fence in fences:
        fence = fence.strip()
        try:
            return json.loads(fence)
        except Exception:
            pass

    # Tenta delimitações externas { ... } ou [ ... ]
    first_brace = raw_text.find("{")
    last_brace = raw_text.rfind("}")
    first_bracket = raw_text.find("[")
    last_bracket = raw_text.rfind("]")

    candidates = []
    if first_brace != -1 and last_brace > first_brace:
        candidates.append((first_brace, raw_text[first_brace:last_brace + 1]))
    if first_bracket != -1 and last_bracket > first_bracket:
        candidates.append((first_bracket, raw_text[first_bracket:last_bracket + 1]))

    candidates.sort(key=lambda x: x[0])
    for _, cand in candidates:
        try:
            return json.loads(cand)
        except Exception:
            pass
    raise ValueError(f"Não foi possível extrair JSON do texto retornado: {raw_text[:300]}")


def translation_schema(batch: list[dict]) -> dict:
    """Restringe a geração aos campos e IDs esperados pelo tradutor."""
    return {
        "type": "object",
        "properties": {"subtitles": {
            "type": "array", "minItems": len(batch), "maxItems": len(batch),
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "enum": [item["id"] for item in batch]},
                    "text": {"type": "string", "minLength": 1},
                },
                "required": ["id", "text"], "additionalProperties": False,
            },
        }},
        "required": ["subtitles"], "additionalProperties": False,
    }


def extract_translations(result, batch: list[dict]) -> dict[int, str]:
    """Valida IDs explícitos; nunca associa uma lista arbitrária por posição."""
    if not isinstance(result, dict) or not isinstance(result.get("subtitles"), list):
        raise ValueError(f"Resposta sem a lista 'subtitles': {str(result)[:300]}")
    translated = {}
    for row in result["subtitles"]:
        if (not isinstance(row, dict) or type(row.get("id")) is not int
                or not isinstance(row.get("text"), str)):
            raise ValueError("Cada fala deve conter id inteiro e text textual.")
        key = row["id"]
        if key in translated:
            raise ValueError(f"A resposta repetiu o ID {key}.")
        translated[key] = row["text"].strip()
    expected = {item["id"] for item in batch}
    if set(translated) != expected or any(not text for text in translated.values()):
        raise ValueError("A resposta omitiu IDs, incluiu IDs inesperados ou texto vazio.")
    return translated


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
    parts.append("Traduza estas falas para português brasileiro:\n" + json.dumps(
        [{"id": x["id"], "text": x["text"]} for x in batch], ensure_ascii=False
    ))
    parts.append('IMPORTANTE: Responda estritamente no formato JSON: {"subtitles": [{"id": 1, "text": "tradução"}]}')
    user_prompt = "\n\n".join(parts)
    payload = {
        "model": MODEL,
        "temperature": 0.2,
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": PROMPT_SISTEMA_COMPLETO},
            {"role": "user", "content": user_prompt + ("\n/no_think" if "qwen" in MODEL.lower() else "")},
        ],
    }
    is_aya = MODEL.startswith("aya-23-")
    request_url = API_URL
    schema = translation_schema(batch)
    if is_aya:
        # Aya 23 uses the original Cohere turn tokens. Native completion accepts
        # the formatted prompt directly and bypasses the chat/PEG output parser.
        prompt = (
            "<BOS_TOKEN><|START_OF_TURN_TOKEN|><|SYSTEM_TOKEN|>" + PROMPT_SISTEMA_COMPLETO
            + "<|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|USER_TOKEN|>" + user_prompt
            + "<|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|CHATBOT_TOKEN|>"
        )
        request_url = urllib.parse.urljoin(API_URL, "/completion")
        payload = {
            "prompt": prompt, "temperature": 0.2, "n_predict": 2048,
            "stream": False, "json_schema": schema,
            "stop": ["<|END_OF_TURN_TOKEN|>", "<|END_OF_TEXT_TOKEN|>"],
        }
    else:
        payload["response_format"] = {"type": "json_object", "schema": schema}
    req = urllib.request.Request(request_url, data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=600) as response:
            response_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            err_content = exc.read().decode("utf-8", errors="replace")
        except Exception:
            err_content = ""
        message = f"Servidor retornou HTTP {exc.code} {exc.reason}: {err_content[:500]}"
        if "peg-" in err_content or exc.code in (401, 403, 404):
            raise LocalServerConfigurationError(message) from exc
        raise RuntimeError(message) from exc
    try:
        data = json.loads(response_body)
    except json.JSONDecodeError as exc:
        excerpt = response_body[:500].replace("\n", "\\n") or "<resposta vazia>"
        raise InvalidModelResponse(f"O servidor local retornou HTTP 200 sem JSON válido na resposta da API: {excerpt}") from exc
    try:
        if is_aya:
            choice = {
                "message": {"content": data["content"]},
                "finish_reason": "length" if data.get("stopped_limit") else "stop",
            }
        else:
            choice = data["choices"][0]
        text = choice["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise InvalidModelResponse(f"Resposta da API sem conteúdo textual de tradução: {str(data)[:500]}") from exc

    if choice.get("finish_reason") == "length":
        raise ValueError("Saída truncada pelo limite de tokens; é necessário reduzir o lote.")
    try:
        result = parse_json_from_text(text)
    except Exception as exc:
        excerpt = text[:500].replace("\n", "\\n") or "<conteúdo vazio>"
        raise InvalidModelResponse(f"O modelo não retornou JSON decodificável ({exc}): {excerpt}") from exc

    return extract_translations(result, batch)


def translate_batch_with_fallbacks(context: list[dict], batch: list[dict]) -> dict[int, str]:
    """Reduz lotes inválidos e falha se não conseguir traduzir uma fala."""
    last_error = None
    for attempt in range(1, 3):
        try:
            return request_batch(context, batch)
        except LocalServerConfigurationError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                print(f"Tentativa {attempt}/2 com lote de {len(batch)} falas falhou: {last_error}", file=sys.stderr, flush=True)
                time.sleep(attempt * 2)

    # Se falhou com o lote atual e tem mais de 3 falas, subdivide na metade
    if len(batch) > 3:
        mid = len(batch) // 2
        print(f"Subdividindo lote de {len(batch)} falas em dois sublotes ({mid} e {len(batch) - mid}) para contornar erro: {last_error}...", flush=True)
        part1 = batch[:mid]
        part2 = batch[mid:]
        res1 = translate_batch_with_fallbacks(context, part1)
        sub_context = list(context)
        for item in part1:
            sub_context.append({"id": item["id"], "text": item["text"], "translation": res1.get(item["id"], "")})
        res2 = translate_batch_with_fallbacks(sub_context[-CONTEXT_WINDOW_SIZE:], part2)
        return {**res1, **res2}

    # Lote pequeno (<= 3 falas): traduz cada fala individualmente
    print(f"Processando {len(batch)} fala(s) individualmente para garantir integridade...", flush=True)
    results = {}
    curr_context = list(context)
    for item in batch:
        item_id = item["id"]
        translated_text = None
        for attempt in range(1, 4):
            try:
                single_res = request_batch(curr_context[-CONTEXT_WINDOW_SIZE:], [item])
                val = single_res.get(item_id, "").strip()
                if val:
                    translated_text = val
                    break
            except LocalServerConfigurationError:
                raise
            except Exception as exc:
                last_error = exc
                print(f"Tentativa {attempt}/3 para fala individual {item_id} falhou: {exc}", file=sys.stderr, flush=True)
                time.sleep(attempt)

        if not translated_text:
            raise RuntimeError(
                f"Não foi possível traduzir a fala {item_id}; o shard está incompleto. "
                f"Os lotes anteriores permanecem no checkpoint. Último erro: {last_error}"
            ) from last_error

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
        f"{TRANSLATION_CACHE_VERSION}\0{MODEL}\0{args.batch_size}\0{PROMPT_SISTEMA_COMPLETO}\0temperature=0.2;max_tokens=2048;json=v1;translategemma-plain-text-v1".encode("utf-8")
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
        context = items[max(0, start - CONTEXT_WINDOW_SIZE):start]
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
