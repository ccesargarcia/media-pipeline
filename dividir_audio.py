#!/usr/bin/env python3
"""Divide um arquivo WAV em N partes em pontos de silêncio para transcrição paralela."""
import argparse
import json
import re
import subprocess
import sys
import wave
from pathlib import Path


def get_wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / float(rate)


def detect_silences(path: Path) -> list[tuple[float, float]]:
    """Detecta intervalos de silêncio (start, end) usando ffmpeg."""
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-i", str(path),
        "-af", "silencedetect=noise=-30dB:d=0.5",
        "-f", "null", "-"
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    silences = []
    current_start = None
    for line in proc.stderr.splitlines():
        start_match = re.search(r"silence_start:\s*([\d.]+)", line)
        if start_match:
            current_start = float(start_match.group(1))
        end_match = re.search(r"silence_end:\s*([\d.]+)", line)
        if end_match and current_start is not None:
            silences.append((current_start, float(end_match.group(1))))
            current_start = None
    return silences


def find_split_points(total_duration: float, silences: list[tuple[float, float]], num_parts: int) -> list[float]:
    """Encontra os melhores pontos de corte próximos dos intervalos ideais."""
    if num_parts <= 1:
        return []
    target_interval = total_duration / num_parts
    split_points = []
    for i in range(1, num_parts):
        target = target_interval * i
        # Procura um silêncio na janela de +/- 60 segundos do ponto ideal
        best_point = target
        best_diff = float("inf")
        for s_start, s_end in silences:
            mid = (s_start + s_end) / 2.0
            diff = abs(mid - target)
            if diff < best_diff and diff <= 60.0:
                best_diff = diff
                best_point = mid
        split_points.append(best_point)
    return sorted(split_points)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entrada_wav", help="Arquivo WAV original")
    parser.add_argument("--parts", type=int, default=4, help="Número de partes (default: 4)")
    parser.add_argument("--output-dir", default="audio_parts", help="Diretório para salvar as partes")
    args = parser.parse_args()

    input_path = Path(args.entrada_wav).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Arquivo WAV não encontrado: {input_path}")

    duration = get_wav_duration(input_path)
    print(f"Duração total do áudio: {duration:.2f}s ({duration/60:.2f} min)", flush=True)

    silences = detect_silences(input_path)
    print(f"Detectados {len(silences)} intervalos de silêncio.", flush=True)

    splits = find_split_points(duration, silences, args.parts)
    print(f"Pontos de corte definidos: {[round(s, 2) for s in splits]}", flush=True)

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Limites de cada parte
    boundaries = [0.0] + splits + [duration]
    offsets = []

    for part_idx in range(args.parts):
        start_t = boundaries[part_idx]
        end_t = boundaries[part_idx + 1]
        part_wav = out_dir / f"part_{part_idx}.wav"

        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start_t:.3f}",
            "-to", f"{end_t:.3f}",
            "-i", str(input_path),
            "-c", "copy",
            str(part_wav)
        ]
        subprocess.run(cmd, check=True)
        print(f"Parte {part_idx} criada: {part_wav.name} ({start_t:.2f}s -> {end_t:.2f}s, dur: {end_t - start_t:.2f}s)", flush=True)
        offsets.append({
            "part": part_idx,
            "filename": part_wav.name,
            "start": round(start_t, 3),
            "end": round(end_t, 3),
            "duration": round(end_t - start_t, 3)
        })

    offsets_file = out_dir / "offsets.json"
    offsets_file.write_text(json.dumps(offsets, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Offsets salvos em: {offsets_file}", flush=True)


if __name__ == "__main__":
    main()
