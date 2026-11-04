#!/usr/bin/env python3
"""
Gera automaticamente as DUAS versões de legendas (.com_orador e pura) em formato .srt e .ass:
1. <stem>.com_orador.pt-BR.srt (com tags de quem fala: Cihan: ..., Alya: ...)
2. <stem>.pt-BR.srt (versão pura sem os nomes)
3. <stem>.com_orador.ass (estilizada com tarja preta e amarelo)
4. <stem>.ass (estilizada com tarja preta e amarelo)
"""
import re
import sys
from pathlib import Path


def parse_time(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    h = int(parts[0])
    m = int(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s


def srt_time_to_ass(seconds: float) -> str:
    hh = int(seconds // 3600)
    mm = int((seconds % 3600) // 60)
    ss = seconds % 60
    return f"{hh}:{mm:02d}:{ss:05.2f}"


ASS_HEADER = """[Script Info]
Title: Legenda PT-BR (Tarja Preta Delimitada + Amarelo)
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,36,&H0000FFFF,&H0000FFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,10,0,2,40,40,68,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def srt_to_ass(srt_path: Path, ass_path: Path):
    content = srt_path.read_text(encoding="utf-8-sig", errors="replace").strip()
    blocks = re.split(r"\r?\n\s*\r?\n", content)

    events = []
    for b in blocks:
        lines = [l.strip() for l in b.splitlines() if l.strip()]
        if len(lines) >= 3 and "-->" in lines[1]:
            start_s, end_s = lines[1].split("-->")
            start = parse_time(start_s)
            end = parse_time(end_s)
            text_lines = lines[2:]
            text_ass = r"\N".join(text_lines)
            ini = srt_time_to_ass(start)
            fim = srt_time_to_ass(end)
            events.append(f"Dialogue: 0,{ini},{fim},Default,,0,0,0,,{text_ass}")

    ass_path.write_text(ASS_HEADER + "\n".join(events) + "\n", encoding="utf-8")
    print(f"Gerado {ass_path.name} com {len(events)} eventos.", flush=True)


SPEAKER_PATTERN = r'(?:\[[^\]]+\]|[A-ZÀ-ÖØ-Þ\u0100-\u017F][A-Za-zÀ-öø-ÿ\u0100-\u017F\.\'\-]+(?:\s+[A-Za-zÀ-öø-ÿ\u0100-\u017F\.\'\-]+){0,2})'


def strip_speaker_tags(text: str) -> str:
    # 1. Início de linha (trata tags simples e duplicadas)
    while True:
        novo = re.sub(r'^(?:-\s*)?' + SPEAKER_PATTERN + r':\s*', '', text)
        if novo == text:
            break
        text = novo
    # 2. Após quebra de linha (\n ou \N)
    while True:
        novo = re.sub(r'(\\N|\n)(?:-\s*)?' + SPEAKER_PATTERN + r':\s*', r'\1', text)
        if novo == text:
            break
        text = novo
    # 3. Após barra divisória /
    while True:
        novo = re.sub(r'(\s*/\s*)(?:-\s*)?' + SPEAKER_PATTERN + r':\s*', r'\1', text)
        if novo == text:
            break
        text = novo
    return text.strip()


def gerar_versoes(input_srt: Path, base_stem: str, output_dir: Path):
    content = input_srt.read_text(encoding="utf-8-sig", errors="replace").strip()
    blocks = re.split(r"\r?\n\s*\r?\n", content)

    tagged_cues = []
    clean_cues = []

    for b in blocks:
        lines = [l.strip() for l in b.splitlines() if l.strip()]
        if len(lines) >= 3 and "-->" in lines[1]:
            idx = lines[0]
            timing = lines[1]
            text = "\n".join(lines[2:]).strip()
            tagged_cues.append((idx, timing, text))

            clean_text = strip_speaker_tags(text)
            if not clean_text:
                clean_text = text
            clean_cues.append((idx, timing, clean_text))

    # 1. Arquivo com orador .srt
    path_tagged_srt = output_dir / f"{base_stem}.com_orador.pt-BR.srt"
    with open(path_tagged_srt, "w", encoding="utf-8") as f:
        for idx, timing, text in tagged_cues:
            f.write(f"{idx}\n{timing}\n{text}\n\n")
    print(f"Gerado: {path_tagged_srt.name}", flush=True)

    # 2. Arquivo puro .srt
    path_clean_srt = output_dir / f"{base_stem}.pt-BR.srt"
    with open(path_clean_srt, "w", encoding="utf-8") as f:
        for idx, timing, text in clean_cues:
            f.write(f"{idx}\n{timing}\n{text}\n\n")
    print(f"Gerado: {path_clean_srt.name}", flush=True)

    # 3. Arquivo com orador .ass
    path_tagged_ass = output_dir / f"{base_stem}.com_orador.ass"
    srt_to_ass(path_tagged_srt, path_tagged_ass)

    # 4. Arquivo puro .ass
    path_clean_ass = output_dir / f"{base_stem}.ass"
    srt_to_ass(path_clean_srt, path_clean_ass)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python3 gerar_versoes_legendas.py input.srt <base_stem> [output_dir]", file=sys.stderr)
        sys.exit(1)
    in_srt = Path(sys.argv[1]).resolve()
    stem = sys.argv[2]
    out_dir = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else in_srt.parent
    gerar_versoes(in_srt, stem, out_dir)
