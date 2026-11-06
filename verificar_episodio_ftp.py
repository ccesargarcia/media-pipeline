#!/usr/bin/env python3
"""
Verifica se um episódio já existe no servidor FTP e possui tamanho mínimo válido.
Retorna código de saída 0 se existe, 1 se não existe.
"""
import argparse
import os
import sys
from ftplib import FTP


def verificar_arquivo_ftp(base_dir: str, filename: str, min_size_mb: int = 150) -> bool:
    host = os.environ.get("FTP_HOST", "192.168.0.1")
    port = int(os.environ.get("FTP_PORT", 21))
    user = os.environ.get("FTP_USER", "")
    password = os.environ.get("FTP_PASSWORD", "")

    if not user:
        print("[FTP] Aviso: FTP_USER não configurado.", file=sys.stderr)
        return False

    try:
        ftp = FTP()
        ftp.connect(host, port, timeout=15)
        ftp.login(user, password)
        try:
            ftp.cwd(base_dir)
        except Exception:
            ftp.quit()
            return False

        tamanho = ftp.size(filename)
        ftp.quit()

        if tamanho and tamanho >= (min_size_mb * 1024 * 1024):
            mb = tamanho / (1024 * 1024)
            print(f"EXISTE:{mb:.1f}MB", flush=True)
            return True
        else:
            print("INEXISTENTE", flush=True)
            return False
    except Exception as e:
        print(f"ERRO:{e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Verifica existência de arquivo no FTP")
    parser.add_argument("dir", help="Diretório base no FTP")
    parser.add_argument("filename", help="Nome do arquivo")
    parser.add_argument("--min-mb", type=int, default=150, help="Tamanho mínimo em MB para considerar válido")
    args = parser.parse_args()

    if verificar_arquivo_ftp(args.dir, args.filename, args.min_mb):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
