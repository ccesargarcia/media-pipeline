#!/usr/bin/env python3
"""
extrair_hardsub_ocr.py
Extrai legendas hardcoded (burned-in) em inglês de vídeos usando FFmpeg + Tesseract OCR.
Otimizado com streaming em memória (sem salvar frames em disco), pré-filtragem por limiar
de luminância (branco puro com borda preta), fusão inteligente de frames similares e
consolidação temporal com difflib para evitar duplicatas e fragmentação.
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import time
from datetime import timedelta
from PIL import Image

try:
    import pytesseract
except ImportError:
    pytesseract = None


def format_srt_time(seconds: float) -> str:
    """Converte segundos float para o formato de tempo SRT: HH:MM:SS,mmm"""
    if seconds < 0:
        seconds = 0
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def get_video_info(video_path: str):
    """Obtém largura, altura, fps e duração do vídeo via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration,r_frame_rate",
        "-of", "json",
        video_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Erro ao analisar vídeo com ffprobe: {res.stderr}")
    data = json.loads(res.stdout)
    stream = data["streams"][0]
    width = int(stream["width"])
    height = int(stream["height"])
    duration = float(stream.get("duration", 0))
    return width, height, duration


def clean_ocr_text(text: str) -> str:
    """Limpa e formata o texto retornado pelo Tesseract."""
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines()]
    clean_lines = []
    for line in lines:
        # Remove caracteres espúrios no início ou fim
        line = re.sub(r"^[\s|~._\-=—*]+", "", line)
        line = re.sub(r"[\s|~_\-=—*]+$", "", line)
        # Corrige aspas curvas comuns
        line = line.replace("“", '"').replace("”", '"').replace("’", "'").replace("`", "'")
        # Remove espaços múltiplos
        line = re.sub(r"\s+", " ", line).strip()
        if line and len(line) > 1:
            clean_lines.append(line)
    return "\n".join(clean_lines)


def text_similarity(s1: str, s2: str) -> float:
    """Retorna o índice de similaridade (0.0 a 1.0) entre duas strings de legenda."""
    s1_norm = " ".join(s1.lower().split())
    s2_norm = " ".join(s2.lower().split())
    if s1_norm == s2_norm:
        return 1.0
    return difflib.SequenceMatcher(None, s1_norm, s2_norm).ratio()


def frame_diff_ratio(bytes1: bytes, bytes2: bytes, threshold: int = 200) -> float:
    """Calcula a proporção de diferença entre dois frames binarizados."""
    if len(bytes1) != len(bytes2) or len(bytes1) == 0:
        return 1.0
    
    diff_count = 0
    total_samples = 0
    for i in range(0, len(bytes1), 4):
        b1 = 1 if bytes1[i] >= threshold else 0
        b2 = 1 if bytes2[i] >= threshold else 0
        if b1 != b2:
            diff_count += 1
        total_samples += 1
    
    return diff_count / total_samples if total_samples > 0 else 0.0


def extract_hardsub(video_path: str, output_srt: str, fps: float = 2.0,
                    crop_pct: float = 0.20, threshold: int = 200,
                    min_white_pixels: int = 90, debug: bool = False):
    """
    Executa a extração completa de hardsubs via streaming de frames e OCR.
    """
    start_wall_time = time.time()
    width, height, duration = get_video_info(video_path)
    
    crop_h = int(height * crop_pct)
    if crop_h % 2 != 0:
        crop_h += 1
    crop_y = height - crop_h
    
    print(f"[*] Vídeo: {os.path.basename(video_path)} ({width}x{height}, Duração: {format_srt_time(duration)})")
    print(f"[*] Faixa de Legenda: Altura={crop_h}px, Y={crop_y} (últimos {int(crop_pct*100)}% da imagem)")
    print(f"[*] Amostragem: {fps} frames/segundo | Limiar de Luminância: >={threshold}")
    
    ffmpeg_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", video_path,
        "-vf", f"fps={fps},crop={width}:{crop_h}:0:{crop_y},format=gray",
        "-f", "rawvideo",
        "-pix_fmt", "gray",
        "-"
    ]
    
    proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frame_bytes_len = width * crop_h
    
    raw_subtitles = []
    active_sub = None
    last_text_frame_raw = None
    
    frame_idx = 0
    ocr_calls = 0
    sec_per_frame = 1.0 / fps
    
    try:
        while True:
            raw = proc.stdout.read(frame_bytes_len)
            if len(raw) < frame_bytes_len:
                break
            
            timestamp = frame_idx * sec_per_frame
            frame_idx += 1
            
            white_count = sum(1 for b in raw[::2] if b >= threshold) * 2
            has_text = white_count >= min_white_pixels
            
            if not has_text:
                if active_sub is not None:
                    active_sub["end"] = timestamp
                    raw_subtitles.append(active_sub)
                    if debug:
                        print(f"[{format_srt_time(active_sub['start'])} --> {format_srt_time(active_sub['end'])}] {repr(active_sub['text'])}")
                    active_sub = None
                    last_text_frame_raw = None
                continue
            
            is_same = False
            if active_sub is not None and last_text_frame_raw is not None:
                diff = frame_diff_ratio(raw, last_text_frame_raw, threshold=threshold)
                if diff < 0.08:  # Até 8% de variação entre quadros = mesma fala
                    is_same = True
                    active_sub["end"] = timestamp + sec_per_frame
            
            if is_same:
                continue
            
            if active_sub is not None:
                active_sub["end"] = timestamp
                raw_subtitles.append(active_sub)
                active_sub = None
            
            # Executa OCR no novo quadro
            img = Image.frombytes("L", (width, crop_h), raw)
            thresh_img = img.point(lambda p: 0 if p >= threshold else 255)
            
            ocr_text = ""
            if pytesseract:
                ocr_text = pytesseract.image_to_string(thresh_img, lang="eng", config="--psm 6")
                ocr_calls += 1
            
            cleaned = clean_ocr_text(ocr_text)
            
            if cleaned:
                active_sub = {
                    "start": timestamp,
                    "end": timestamp + sec_per_frame,
                    "text": cleaned
                }
                last_text_frame_raw = raw
            else:
                last_text_frame_raw = None
                
            if frame_idx % int(fps * 60) == 0:
                elapsed = time.time() - start_wall_time
                pos_pct = (timestamp / duration * 100) if duration > 0 else 0
                print(f"[*] Progresso: {pos_pct:5.1f}% ({format_srt_time(timestamp)} / {format_srt_time(duration)}) - {len(raw_subtitles)} blocos, {ocr_calls} OCRs, tempo: {elapsed:.1f}s")
                
    finally:
        proc.stdout.close()
        proc.wait()
        
    if active_sub is not None:
        raw_subtitles.append(active_sub)
    
    print(f"[*] Extração bruta: {len(raw_subtitles)} blocos brutos em {time.time() - start_wall_time:.1f}s")
    
    # Consolidação inteligente com fusão por similaridade e eliminação de ruídos
    consolidated = []
    for sub in raw_subtitles:
        txt = sub["text"].strip()
        dur = sub["end"] - sub["start"]
        
        # Ignora ruídos ultracurtos (< 0.5s e menos de 4 letras)
        if dur < 0.5 and len(txt) < 4:
            continue
            
        if not txt:
            continue
            
        if consolidated:
            prev = consolidated[-1]
            gap = sub["start"] - prev["end"]
            sim = text_similarity(prev["text"], txt)
            
            # Se a legenda for igual ou muito similar (>= 75%) e o intervalo for menor que 1.2s:
            if sim >= 0.75 and gap <= 1.2:
                # Mantém o texto mais longo/completo e estende o fim
                if len(txt) > len(prev["text"]):
                    prev["text"] = txt
                prev["end"] = sub["end"]
                continue
                
        consolidated.append(sub)
    
    # Formata e grava o arquivo SRT
    with open(output_srt, "w", encoding="utf-8") as f:
        for idx, sub in enumerate(consolidated, 1):
            start_str = format_srt_time(sub["start"])
            end_str = format_srt_time(max(sub["end"], sub["start"] + 0.8))
            f.write(f"{idx}\n{start_str} --> {end_str}\n{sub['text']}\n\n")
            
    total_time = time.time() - start_wall_time
    print(f"[✓] Sucesso! Gerado arquivo SRT consolidado com {len(consolidated)} legendas: {output_srt}")
    print(f"[✓] Tempo total de OCR: {total_time:.1f}s ({total_time/60:.1f} min)")


def main():
    parser = argparse.ArgumentParser(description="Extrai legendas hardcoded em inglês de vídeo via OCR.")
    parser.add_argument("video", help="Caminho do arquivo de vídeo (.mp4, .mkv)")
    parser.add_argument("output_srt", help="Caminho de saída para o arquivo .srt gerado")
    parser.add_argument("--fps", type=float, default=2.0, help="Frames por segundo analisados (padrão: 2.0)")
    parser.add_argument("--crop-pct", type=float, default=0.20, help="Fração inferior da imagem a recortar (padrão: 0.20)")
    parser.add_argument("--threshold", type=int, default=200, help="Limiar de brilho dos caracteres brancos (0-255, padrão: 200)")
    parser.add_argument("--debug", action="store_true", help="Imprime cada legenda detectada em tempo real")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.video):
        print(f"Erro: Arquivo de vídeo '{args.video}' não encontrado.", file=sys.stderr)
        sys.exit(1)
        
    extract_hardsub(
        video_path=args.video,
        output_srt=args.output_srt,
        fps=args.fps,
        crop_pct=args.crop_pct,
        threshold=args.threshold,
        debug=args.debug
    )


if __name__ == "__main__":
    main()
