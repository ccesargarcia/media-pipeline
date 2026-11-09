#!/usr/bin/env python3
"""
Download paralelo via FTP (4 conexões simultâneas respeitando o limite de 5 sessões do roteador TP-Link),
compatível com SOCKS5 (ALL_PROXY=socks5h://...) e com fallback automático para curl tradicional.
"""
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


def get_remote_size(url: str, user: str, password: str) -> int:
    cmd = ["curl", "-sI", "--ftp-pasv", "-u", f"{user}:{password}", url]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    m = re.search(r"Content-Length:\s*(\d+)", res.stdout, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 0


def download_chunk(idx: int, start: int, end: int, url: str, user: str, password: str, part_file: str) -> bool:
    expected_len = end - start + 1
    for attempt in range(1, 7):
        current_len = os.path.getsize(part_file) if os.path.exists(part_file) else 0
        if current_len >= expected_len:
            return True
        cur_start = start + current_len
        cmd = [
            "curl", "-sS", "--fail", "--ftp-pasv",
            "--retry", "3", "--retry-delay", "2",
            "-u", f"{user}:{password}",
            "-r", f"{cur_start}-{end}",
            url,
        ]
        with open(part_file, "ab") as f:
            proc = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE)
        if os.path.exists(part_file) and os.path.getsize(part_file) == expected_len:
            return True
        time.sleep(2 * attempt)
    return os.path.exists(part_file) and os.path.getsize(part_file) == expected_len


def fallback_single_curl(url: str, user: str, password: str, output_file: str) -> int:
    print("⚠️ Acionando fallback para download em conexão única (curl -C -)...", flush=True)
    cmd = [
        "curl", "-#", "--fail", "--ftp-pasv",
        "--retry", "5", "--retry-delay", "5", "--retry-connrefused",
        "-C", "-",
        "-u", f"{user}:{password}",
        url, "-o", output_file,
    ]
    return subprocess.call(cmd)


def main():
    if len(sys.argv) < 3:
        print("Uso: baixar_ftp_paralelo.py <ftp_url> <output_file> [workers=4]", file=sys.stderr)
        sys.exit(2)

    url = sys.argv[1]
    output_file = sys.argv[2]
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    user = os.environ.get("FTP_USER", "")
    password = os.environ.get("FTP_PASSWORD", "")

    t0 = time.time()
    total_size = get_remote_size(url, user, password)
    if total_size <= 10 * 1024 * 1024:
        # Se não conseguiu obter tamanho ou arquivo < 10MB, usa curl direto
        sys.exit(fallback_single_curl(url, user, password, output_file))

    total_mb = total_size / (1024 * 1024)
    print(f"🚀 Iniciando download paralelo em {workers} conexões simultâneas ({total_mb:.1f} MB)...", flush=True)

    chunk_size = total_size // workers
    ranges = []
    for i in range(workers):
        s = i * chunk_size
        e = (total_size - 1) if i == workers - 1 else (s + chunk_size - 1)
        part_file = f"{output_file}.part{i}"
        if os.path.exists(part_file):
            os.remove(part_file)
        ranges.append((i, s, e, part_file))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(download_chunk, i, s, e, url, user, password, pf): (i, pf)
            for (i, s, e, pf) in ranges
        }
        while not all(f.done() for f in futures):
            time.sleep(5)
            downloaded = sum(os.path.getsize(pf) if os.path.exists(pf) else 0 for (_, _, _, pf) in ranges)
            elapsed = max(0.1, time.time() - t0)
            speed_mbs = (downloaded / (1024 * 1024)) / elapsed
            pct = (downloaded / total_size) * 100
            print(
                f"⏱️ [{int(elapsed)}s] Progresso: {pct:5.1f}% ({downloaded / (1024*1024):6.1f} / {total_mb:.1f} MB) "
                f"| Velocidade média: {speed_mbs:.2f} MB/s",
                flush=True,
            )

        ok_all = all(f.result() for f in futures)

    if not ok_all:
        for (_, _, _, pf) in ranges:
            if os.path.exists(pf):
                os.remove(pf)
        sys.exit(fallback_single_curl(url, user, password, output_file))

    # Concatena as partes na ordem exata
    with open(output_file, "wb") as out_f:
        for (_, _, _, pf) in ranges:
            with open(pf, "rb") as in_f:
                shutil.copyfileobj(in_f, out_f, length=4 * 1024 * 1024)
            os.remove(pf)

    elapsed = time.time() - t0
    final_size = os.path.getsize(output_file)
    if final_size != total_size:
        print(f"❌ Tamanho final ({final_size}) diferente do esperado ({total_size}).", file=sys.stderr)
        os.remove(output_file)
        sys.exit(fallback_single_curl(url, user, password, output_file))

    print(
        f"✅ Download concluído em {elapsed:.1f}s ({elapsed/60:.1f} min) "
        f"| Velocidade média: {(total_mb / elapsed):.2f} MB/s!",
        flush=True,
    )


if __name__ == "__main__":
    main()
