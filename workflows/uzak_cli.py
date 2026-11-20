#!/usr/bin/env python3
"""
CLI auxiliar universal (funciona no Codex CLI, Antigravity ou terminal)
para o pipeline em 2 passagens de Uzak Şehir (Longe Demais).

Subcomandos:
  prepare <ep>      Prepara work_uzak_sehir/ep<ep>/ com 4 chunks + contexto anterior
  make-review <ep>  Gera review_chunk1..4.txt (EN vs PT lado a lado) para QA
  finalize <ep>     Aplica fixes_chunk*.json, gera .srt/.ass, valida linter e distribui
"""
import argparse
import ftplib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

MEDIA_DIR = Path("/data/data/com.termux/files/home/media-pipeline")
FTP_HOST = "192.168.0.1"
FTP_USER = "admin"
FTP_PASS = "63274c0954"


def get_work_dir(ep: int) -> Path:
    d = MEDIA_DIR / "work_uzak_sehir" / f"ep{ep}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_prepare(args):
    ep = args.episode
    season = args.season
    work = get_work_dir(ep)
    stem = f"Uzak_Sehir_-_Episode_{ep:02d}"
    en_srt = work / f"{stem}.en.srt"

    if not en_srt.exists():
        # Procura em backups locais antes de baixar do FTP
        candidates = list(Path("/data/data/com.termux/files/home/.gemini/antigravity-cli/brain").glob(f"*/scratch/en_backup/{stem}.en.srt"))
        candidates.append(MEDIA_DIR / "legendas_prontas" / f"{stem}.en.srt")
        found = next((p for p in candidates if p.exists()), None)
        if found:
            shutil.copy2(found, en_srt)
            print(f"[OK] Copiado de: {found}")
        else:
            print(f"[FTP] Baixando {stem}.en.srt de /G/Series/Longe demais - {season}...")
            ftp = ftplib.FTP(FTP_HOST, timeout=15)
            ftp.login(FTP_USER, FTP_PASS)
            ftp.cwd(f"/G/Series/Longe demais - {season}")
            with open(en_srt, "wb") as fp:
                ftp.retrbinary(f"RETR {stem}.en.srt", fp.write)
            ftp.quit()
            print(f"[OK] Baixado do FTP: {en_srt}")

    raw_blocks = [b.strip() for b in en_srt.read_text(encoding="utf-8-sig").strip().split("\n\n") if b.strip()]
    total = len(raw_blocks)
    chunk_size = math.ceil(total / 4)
    meta = []

    for cid in range(1, 5):
        s = (cid - 1) * chunk_size
        e = min(total, cid * chunk_size)
        if s >= total:
            break
        c_blocks = raw_blocks[s:e]
        first_id = int(c_blocks[0].splitlines()[0])
        last_id = int(c_blocks[-1].splitlines()[0])

        (work / f"chunk{cid}.en.srt").write_text("\n\n".join(c_blocks) + "\n", encoding="utf-8")

        compact = []
        if s > 0:
            compact.append("=== CONTEXTO ANTERIOR (APENAS REFERÊNCIA — NÃO TRADUZIR) ===")
            for pb in raw_blocks[max(0, s - 5):s]:
                pl = pb.splitlines()
                compact.append(f"[CTX #{pl[0]}]: {' | '.join(pl[2:])}")
            compact.append("=== INÍCIO DO CHUNK PARA TRADUZIR ===")
        for b in c_blocks:
            bl = b.splitlines()
            compact.append(f"{bl[0]}: {' | '.join(bl[2:])}")

        (work / f"chunk{cid}_compact.txt").write_text("\n".join(compact) + "\n", encoding="utf-8")
        meta.append({"chunk": cid, "first_id": first_id, "last_id": last_id, "count": len(c_blocks)})

    print(json.dumps({"episode": ep, "total_blocks": total, "work_dir": str(work), "chunks": meta}, indent=2))


def cmd_make_review(args):
    ep = args.episode
    work = get_work_dir(ep)
    for cid in range(1, 5):
        en_p = work / f"chunk{cid}.en.srt"
        pt_p = work / f"chunk{cid}.pt-BR.srt"
        if not en_p.exists():
            continue
        if not pt_p.exists():
            sys.exit(f"Erro: arquivo traduzido não encontrado: {pt_p}")
        en_b = [b.strip() for b in en_p.read_text(encoding="utf-8-sig").strip().split("\n\n") if b.strip()]
        pt_b = [b.strip() for b in pt_p.read_text(encoding="utf-8-sig").strip().split("\n\n") if b.strip()]
        if len(en_b) != len(pt_b):
            sys.exit(f"Erro Chunk {cid}: EN={len(en_b)} != PT={len(pt_b)}")
        lines = []
        for eb, pb in zip(en_b, pt_b):
            el, pl = eb.splitlines(), pb.splitlines()
            lines.append(f"#{el[0]}\nEN: {' / '.join(el[2:])}\nPT: {' / '.join(pl[2:])}")
        out = work / f"review_chunk{cid}.txt"
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"[OK] Gerado {out} ({len(en_b)} blocos)")


def cmd_finalize(args):
    ep = args.episode
    season = args.season
    work = get_work_dir(ep)
    stem = f"Uzak_Sehir_-_Episode_{ep:02d}"
    en_srt = work / f"{stem}.en.srt"

    total_expected = len([b.strip() for b in en_srt.read_text(encoding="utf-8-sig").strip().split("\n\n") if b.strip()])

    all_fixes = {}
    for cid in range(1, 5):
        fp = work / f"fixes_chunk{cid}.json"
        if fp.exists():
            data = json.loads(fp.read_text(encoding="utf-8"))
            for k, v in data.items():
                all_fixes[int(k)] = v.strip()

    final_blocks = []
    for cid in range(1, 5):
        pt_p = work / f"chunk{cid}.pt-BR.srt"
        if not pt_p.exists():
            continue
        for b in [x.strip() for x in pt_p.read_text(encoding="utf-8-sig").strip().split("\n\n") if x.strip()]:
            lines = b.splitlines()
            idx = int(lines[0])
            timing = lines[1]
            if idx in all_fixes:
                final_blocks.append(f"{idx}\n{timing}\n{all_fixes[idx]}")
            else:
                final_blocks.append(b)

    if len(final_blocks) != total_expected:
        sys.exit(f"Erro de paridade: final={len(final_blocks)} != original={total_expected}")

    com_orador = work / f"{stem}.com_orador.pt-BR.srt"
    com_orador.write_text("\n\n".join(final_blocks) + "\n", encoding="utf-8")
    print(f"[OK] Mesclados {len(final_blocks)} blocos ({len(all_fixes)} correções QA aplicadas).")

    subprocess.run(["python3", str(MEDIA_DIR / "gerar_versoes_legendas.py"), str(com_orador), stem, str(work)], check=True)

    pt_srt = work / f"{stem}.pt-BR.srt"
    lint_res = subprocess.run(
        ["python3", str(MEDIA_DIR / "lint_legendas.py"), "-o", str(en_srt), "--json", str(pt_srt)],
        capture_output=True, text=True, check=True,
    )
    lint_json = json.loads(lint_res.stdout)
    print(f"[LINT] valido={lint_json['valido']} | falas={lint_json['total_falas']} | erros={len(lint_json['erros'])} | inconsistencias={len(lint_json['inconsistencias_regras'])}")
    if not lint_json["valido"] or lint_json["erros"]:
        print("ERROS:", lint_json["erros"])
        sys.exit(1)

    if args.no_distribute:
        print("[SKIP] Distribuição ignorada (--no-distribute).")
        return

    deliverables = [
        work / f"{stem}.pt-BR.srt",
        work / f"{stem}.ass",
        work / f"{stem}.com_orador.pt-BR.srt",
        work / f"{stem}.com_orador.ass",
    ]

    local_dir = Path("/sdcard/Download/Longe Demais")
    local_dir.mkdir(parents=True, exist_ok=True)
    for f in deliverables:
        shutil.copy2(f, local_dir / f.name)
    print(f"[LOCAL] 4 arquivos copiados para {local_dir}")

    ftp = ftplib.FTP(FTP_HOST, timeout=20)
    ftp.login(FTP_USER, FTP_PASS)
    ftp.cwd(f"/G/Series/Longe demais - {season}")
    for f in deliverables:
        with open(f, "rb") as fp:
            ftp.storbinary(f"STOR {f.name}", fp)
    ftp.quit()
    print(f"[FTP] 4 arquivos enviados para /G/Series/Longe demais - {season}")

    tmp_a70 = f"/data/data/com.termux/files/home/tmp_ep{ep}_push"
    subprocess.run(["ssh", "a70", f"mkdir -p {tmp_a70}"], check=True)
    for f in deliverables:
        subprocess.run(["scp", "-q", str(f), f"a70:{tmp_a70}/{f.name}"], check=True)
    devs = subprocess.run(["ssh", "a70", "adb devices"], capture_output=True, text=True).stdout
    target_dev = "emulator-5554" if "emulator-5554" in devs else "192.168.0.218:5555"
    for f in deliverables:
        subprocess.run(["ssh", "a70", f"adb -s {target_dev} push {tmp_a70}/{f.name} /sdcard/Download/"], check=False)
        subprocess.run(["ssh", "a70", f"adb -s {target_dev} push {tmp_a70}/{f.name} /sdcard/Android/data/org.courville.nova/cache/subtitles/"], check=False)
    subprocess.run(["ssh", "a70", f"rm -rf {tmp_a70}"], check=True)
    print(f"[FIRE TV] 4 arquivos enviados para {target_dev} (Download + Nova cache)")


def main():
    p = argparse.ArgumentParser(description="CLI de tradução 2-pass para Uzak Şehir")
    sub = p.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("prepare")
    p1.add_argument("episode", type=int)
    p1.add_argument("--season", default="Segunda Temporada")
    p1.set_defaults(func=cmd_prepare)

    p2 = sub.add_parser("make-review")
    p2.add_argument("episode", type=int)
    p2.set_defaults(func=cmd_make_review)

    p3 = sub.add_parser("finalize")
    p3.add_argument("episode", type=int)
    p3.add_argument("--season", default="Segunda Temporada")
    p3.add_argument("--no-distribute", action="store_true")
    p3.set_defaults(func=cmd_finalize)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
