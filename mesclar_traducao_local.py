#!/usr/bin/env python3
"""Reúne as quatro partes traduzidas do SRT, validando IDs e cobertura."""
import argparse
import json
import re
from pathlib import Path


def parse_srt(content: str) -> list[dict[str, str]]:
    items = []
    for block in re.split(r"\r?\n\s*\r?\n", content.strip()):
        lines = block.splitlines()
        if len(lines) >= 3 and "-->" in lines[1]:
            items.append({"idx": lines[0].strip(), "time": lines[1].strip(), "text": "\n".join(lines[2:]).strip()})
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entrada")
    parser.add_argument("saida")
    parser.add_argument("partes", nargs="+")
    args = parser.parse_args()

    source = Path(args.entrada)
    raw = source.read_bytes()
    content = raw.decode("utf-16") if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else raw.decode("utf-8-sig", errors="replace")
    items = parse_srt(content)
    if not items:
        raise ValueError("Nenhuma fala SRT válida foi encontrada.")

    translations: dict[int, str] = {}
    for part_path in args.partes:
        part = json.loads(Path(part_path).read_text(encoding="utf-8"))
        if not isinstance(part, dict):
            raise ValueError(f"Parte inválida: {part_path}")
        for raw_id, raw_text in part.items():
            cue_id = int(raw_id)
            if cue_id in translations:
                raise ValueError(f"ID duplicado entre partes: {cue_id}")
            if not isinstance(raw_text, str) or not raw_text.strip():
                raise ValueError(f"Tradução vazia para o ID {cue_id}")
            translations[cue_id] = raw_text.strip()

    expected = set(range(1, len(items) + 1))
    if set(translations) != expected:
        missing = sorted(expected - set(translations))
        extra = sorted(set(translations) - expected)
        raise ValueError(f"Partes incompletas ou inválidas; ausentes={missing[:10]}, inesperados={extra[:10]}")

    blocks = [f"{item['idx']}\n{item['time']}\n{translations[i]}" for i, item in enumerate(items, 1)]
    output = Path(args.saida)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    print(f"Tradução local reunida: {output}")


if __name__ == "__main__":
    main()
