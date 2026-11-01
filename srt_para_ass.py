#!/usr/bin/env python3
"""
Converte arquivo .srt para .ass (Advanced SubStation Alpha) com:
- Tarja preta 100% opaca cobrindo a área de legendas embutidas (hardsub) do vídeo
- Texto em amarelo vivo (#FFFF00) em negrito centralizado sobre a tarja preta
Suportado nativamente pelo VLC (Android / PC) sem precisar recodificar o vídeo.
"""
import re
import sys
from pathlib import Path


def srt_time_to_ass(t: str, offset_sec: float = 0.0) -> str:
    t = t.strip().replace(",", ".")
    h, m, s = t.split(":")
    total = max(0.0, int(h) * 3600 + int(m) * 60 + float(s) + offset_sec)
    hh = int(total // 3600)
    mm = int((total % 3600) // 60)
    ss = total % 60
    return f"{hh}:{mm:02d}:{ss:05.2f}"


def converter_srt_para_ass(srt_path: Path, ass_path: Path = None):
    if ass_path is None:
        ass_path = srt_path.with_suffix(".ass")

    header = """[Script Info]
Title: Legenda PT-BR (Tarja Preta Opaca + Amarelo)
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Box,sans-serif,42,&H00000000,&H00000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Default,sans-serif,42,&H0000FFFF,&H0000FFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,14,0,2,60,60,48,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    conteudo = srt_path.read_text(encoding="utf-8-sig", errors="replace").strip()
    blocos = re.split(r"\r?\n\s*\r?\n", conteudo)
    events = []
    for b in blocos:
        linhas = [l.rstrip("\r") for l in b.splitlines()]
        if len(linhas) >= 3 and "-->" in linhas[1]:
            ini_s, fim_s = linhas[1].split("-->")
            # A tarja preta abre 0.15s antes e fecha 0.25s depois para cobrir a legenda original de baixo
            ini_box = srt_time_to_ass(ini_s, -0.15)
            fim_box = srt_time_to_ass(fim_s, 0.25)
            ini = srt_time_to_ass(ini_s)
            fim = srt_time_to_ass(fim_s)
            txt = "\\N".join(l.strip() for l in linhas[2:] if l.strip())
            events.append(
                f"Dialogue: 0,{ini_box},{fim_box},Box,,0,0,0,,{{\\pos(0,0)\\p1}}m 120 555 l 1160 555 1160 695 120 695{{\\p0}}"
            )
            events.append(f"Dialogue: 1,{ini},{fim},Default,,0,0,0,,{txt}")

    ass_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return ass_path, len(events) // 2


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Uso: python3 {sys.argv[0]} arquivo.srt [saida.ass]", file=sys.stderr)
        sys.exit(1)
    entrada = Path(sys.argv[1]).expanduser()
    saida = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else None
    out, n = converter_srt_para_ass(entrada, saida)
    print(f"==> Legenda .ass (tarja preta opaca + amarelo) gerada em: {out} ({n} falas)")
