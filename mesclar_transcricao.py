#!/usr/bin/env python3
"""Mescla transcrições parciais SRT aplicando os offsets de tempo calculados na divisão do áudio."""
import argparse
import json
import re
from pathlib import Path


def parse_time(time_str: str) -> float:
    match = re.fullmatch(r"(\d+):(\d+):(\d+)[,\.](\d+)", time_str.strip())
    if not match:
        raise ValueError(f"Timestamp inválido: {time_str}")
    h, m, s, ms = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000.0


def format_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        s += 1
        ms -= 1000
    if s >= 60:
        m += 1
        s -= 60
    if m >= 60:
        h += 1
        m -= 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(content: str) -> list[dict]:
    items = []
    if not content.strip():
        return items
    for block_number, block in enumerate(re.split(r"\r?\n\s*\r?\n", content.strip()), 1):
        lines = block.splitlines()
        if len(lines) < 3 or "-->" not in lines[1] or not lines[0].strip():
            raise ValueError(f"Bloco SRT inválido na posição {block_number}.")
        time_parts = lines[1].split("-->", 1)
        text = "\n".join(lines[2:]).strip()
        if len(time_parts) != 2 or not text:
            raise ValueError(f"Bloco SRT incompleto na posição {block_number}.")
        start, end = parse_time(time_parts[0]), parse_time(time_parts[1])
        if end <= start:
            raise ValueError(f"Bloco SRT com intervalo inválido na posição {block_number}.")
        items.append({"start": start, "end": end, "text": text})
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("offsets_json", help="Arquivo offsets.json gerado pelo dividir_audio.py")
    parser.add_argument("saida_srt", help="Arquivo SRT final unificado")
    parser.add_argument("partes_srt", nargs="+", help="Arquivos SRT das partes")
    args = parser.parse_args()

    offsets_info = json.loads(Path(args.offsets_json).read_text(encoding="utf-8"))
    offset_by_part = {item["part"]: item["start"] for item in offsets_info}
    expected_parts = set(offset_by_part)
    if len(expected_parts) != len(offsets_info) or not expected_parts:
        raise ValueError("Metadados de áudio inválidos: índices de parte ausentes ou duplicados.")
    if expected_parts != set(range(len(offsets_info))):
        raise ValueError("Metadados de áudio inválidos: os índices das partes precisam ser contínuos a partir de zero.")

    # Mapear arquivos srt por índice de parte
    # Espera nomes como part_0.srt, part-0.srt, ou lista ordenada
    srt_by_part = {}
    for srt_path in args.partes_srt:
        p = Path(srt_path)
        match = re.search(r"part[_-](\d+)", p.stem)
        if match:
            part_idx = int(match.group(1))
            if part_idx in srt_by_part:
                raise ValueError(f"Mais de um SRT recebido para a parte {part_idx}.")
            srt_by_part[part_idx] = p
        else:
            raise ValueError(f"Não foi possível identificar o índice da parte em {p.name}.")

    received_parts = set(srt_by_part)
    if received_parts != expected_parts:
        missing = sorted(expected_parts - received_parts)
        unexpected = sorted(received_parts - expected_parts)
        raise ValueError(f"Transcrições parciais incompletas; ausentes={missing}, inesperadas={unexpected}.")

    combined_cues = []
    for part_idx in sorted(srt_by_part.keys()):
        p = srt_by_part[part_idx]
        offset = offset_by_part.get(part_idx, 0.0)
        raw = p.read_bytes()
        content = raw.decode("utf-16") if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else raw.decode("utf-8-sig", errors="replace")
        cues = parse_srt(content)
        print(f"Parte {part_idx} ({p.name}): {len(cues)} falas, offset aplicado: +{offset:.2f}s", flush=True)
        for cue in cues:
            cue["start"] += offset
            cue["end"] += offset
            combined_cues.append(cue)

    # Ordenar por tempo de início e re-indexar
    combined_cues.sort(key=lambda x: x["start"])
    if not combined_cues:
        raise ValueError("As partes foram recebidas, mas nenhuma fala foi transcrita.")

    blocks = []
    for idx, cue in enumerate(combined_cues, 1):
        time_line = f"{format_time(cue['start'])} --> {format_time(cue['end'])}"
        blocks.append(f"{idx}\n{time_line}\n{cue['text']}")

    out_file = Path(args.saida_srt)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    print(f"Transcrição unificada com sucesso: {out_file} ({len(blocks)} falas totais)", flush=True)


if __name__ == "__main__":
    main()
