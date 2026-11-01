#!/usr/bin/env python3
"""
Converte arquivo .srt para .ass (Advanced SubStation Alpha) e normaliza timings:
- Elimina o congelamento de legendas durante músicas instrumentais ou pausas dramáticas.
- Ajusta a duração de cada fala baseando-se na velocidade de leitura humana confortável (15-18 caracteres/segundo).
- Limita falas a no máximo 6.0 segundos (ou 7.5s para falas muito extensas).
- Garante intervalo limpo sem legenda durante trilha sonora e silêncio.
- Remove marcadores fantasmas como '[Música]'.
- Tarja preta 100% opaca cobrindo a área de legendas embutidas (hardsub) do vídeo.
- Texto em amarelo vivo (#FFFF00) em negrito centralizado sobre a tarja preta.
Suportado nativamente pelo VLC (Android / PC / TV) sem precisar recodificar o vídeo.
"""
import re
import sys
from pathlib import Path


def parse_time(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def format_time_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def srt_time_to_ass(seconds: float) -> str:
    hh = int(seconds // 3600)
    mm = int((seconds % 3600) // 60)
    ss = seconds % 60
    return f"{hh}:{mm:02d}:{ss:05.2f}"


def converter_srt_para_ass(srt_path: Path, ass_path: Path = None, atualizar_srt: bool = True):
    if ass_path is None:
        clean_stem = srt_path.name.replace(".pt-BR.srt", "").replace(".srt", "")
        ass_path = srt_path.with_name(f"{clean_stem}.ass")

    conteudo = srt_path.read_text(encoding="utf-8-sig", errors="replace").strip()
    raw_blocks = re.split(r"\r?\n\s*\r?\n", conteudo)

    parsed = []
    for b in raw_blocks:
        lines = [l.strip() for l in b.splitlines() if l.strip()]
        if len(lines) >= 3 and "-->" in lines[1]:
            start_s, end_s = lines[1].split("-->")
            start = parse_time(start_s)
            end = parse_time(end_s)
            text = "\n".join(lines[2:]).strip()

            # Pula marcadores isolados de música
            if text.lower().strip() in ["[música]", "[musica]", "[music]", "(música)", "(musica)"]:
                continue

            parsed.append({"start": start, "end": end, "text": text})

    for i, item in enumerate(parsed):
        clean_text = re.sub(r"<[^>]+>", "", item["text"]).strip()
        num_chars = len(clean_text)

        # Tempo ideal de leitura humana
        dur_ideal = max(1.8, num_chars * 0.065 + 0.6)
        dur_maxima = 7.5 if num_chars > 85 else 6.0
        dur_ajustada = min(dur_ideal, dur_maxima)

        # Se a legenda foi esticada sobre a música ou silêncio, corta no fim natural da fala
        if (item["end"] - item["start"]) > dur_ajustada:
            item["end"] = item["start"] + dur_ajustada

        # Evita colisão com a fala seguinte, garantindo um intervalo mínimo
        if i + 1 < len(parsed):
            next_start = parsed[i + 1]["start"]
            if item["end"] > next_start - 0.08:
                item["end"] = max(item["start"] + 0.8, next_start - 0.08)

    # Gravar SRT normalizado
    if atualizar_srt:
        srt_lines = []
        for idx, item in enumerate(parsed, start=1):
            t_srt = f"{format_time_srt(item['start'])} --> {format_time_srt(item['end'])}"
            srt_lines.append(f"{idx}\n{t_srt}\n{item['text']}")
        srt_path.write_text("\n\n".join(srt_lines) + "\n", encoding="utf-8")

    # Gerar ASS com estilo caixa preta + texto amarelo
    ass_header = """[Script Info]
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
    ass_events = []
    for item in parsed:
        ini_box = srt_time_to_ass(max(0.0, item["start"] - 0.12))
        fim_box = srt_time_to_ass(item["end"] + 0.15)
        ini = srt_time_to_ass(item["start"])
        fim = srt_time_to_ass(item["end"])

        txt_ass = r"\N".join(l.strip() for l in item["text"].splitlines() if l.strip())

        ass_events.append(
            f"Dialogue: 0,{ini_box},{fim_box},Box,,0,0,0,,"
            f"{{\\pos(0,0)\\p1}}m 120 555 l 1160 555 1160 695 120 695{{\\p0}}"
        )
        ass_events.append(f"Dialogue: 1,{ini},{fim},Default,,0,0,0,,{txt_ass}")

    ass_path.write_text(ass_header + "\n".join(ass_events) + "\n", encoding="utf-8")
    return ass_path, len(parsed)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Uso: python3 {sys.argv[0]} arquivo.srt [saida.ass]", file=sys.stderr)
        sys.exit(1)
    entrada = Path(sys.argv[1]).expanduser()
    saida = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else None
    out, n = converter_srt_para_ass(entrada, saida)
    print(f"==> Legenda .ass e .srt sincronizados gerados em: {out} ({n} falas)")
