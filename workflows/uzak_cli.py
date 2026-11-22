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
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

MEDIA_DIR = Path("/data/data/com.termux/files/home/media-pipeline")
FTP_HOST = "192.168.0.1"
FTP_USER = "admin"
FTP_PASS = "63274c0954"


def fetch_en_srt_subtitlecat(ep: int):
    """Busca e baixa automaticamente a melhor legenda .en.srt no SubtitleCat (prioriza setwillow6a/sebeder)."""
    queries = [f"Uzak+Sehir+{ep}", f"Uzak+Sehir+{ep}.+Bolum"]
    candidate_pages = []
    seen = set()
    for q in queries:
        url = f"https://www.subtitlecat.com/index.php?search={q}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="ignore")
        except Exception:
            continue
        for href, title in re.findall(r'href="(subs/[^"]+)"[^>]*>([^<]+)<', html):
            if href in seen:
                continue
            if re.search(rf"(?<!\d){ep}(?!\d)", title) and "uzak" in title.lower():
                seen.add(href)
                # Evita priorizar auto-generated se houver humana
                is_auto = "auto-generated" in title.lower()
                candidate_pages.append((is_auto, title, "https://www.subtitlecat.com/" + href))

    candidate_pages.sort(key=lambda x: x[0])
    best = None
    for is_auto, title, page_url in candidate_pages:
        try:
            req = urllib.request.Request(page_url, headers={"User-Agent": "Mozilla/5.0"})
            html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="ignore")
        except Exception:
            continue
        srts = re.findall(r'href="([^"]+\.srt)"', html)
        en_srts = [s for s in srts if s.lower().endswith("-en.srt") or s.lower().endswith("en.srt")]
        for s in en_srts:
            dl_url = "https://www.subtitlecat.com" + urllib.parse.quote(s) if s.startswith("/") else s
            try:
                data = urllib.request.urlopen(
                    urllib.request.Request(dl_url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20
                ).read().decode("utf-8-sig", errors="replace")
                blocks = [b.strip() for b in data.strip().replace("\r\n", "\n").split("\n\n") if b.strip()]
                if len(blocks) < 500:
                    continue
                is_official = ("setwillow6a" in data.lower()) or ("sebeder.org" in data.lower())
                clean_text = "\n\n".join(blocks) + "\n"
                if is_official:
                    return clean_text, s, len(blocks), True
                if best is None or (not is_auto and best[3] == "auto") or len(blocks) > best[2]:
                    best = (clean_text, s, len(blocks), "auto" if is_auto else "human")
            except Exception:
                continue
    return best


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

    if en_srt.exists() and en_srt.stat().st_size == 0:
        en_srt.unlink()

    if not en_srt.exists():
        # Procura em backups locais antes de baixar do FTP
        candidates = list(Path("/data/data/com.termux/files/home/.gemini/antigravity-cli/brain").glob(f"*/scratch/en_backup/{stem}.en.srt"))
        candidates.append(MEDIA_DIR / "legendas_prontas" / f"{stem}.en.srt")
        found = next((p for p in candidates if p.exists() and p.stat().st_size > 0), None)
        if found:
            shutil.copy2(found, en_srt)
            print(f"[OK] Copiado de: {found}")
        else:
            print(f"[FTP] Baixando {stem}.en.srt de /G/Series/Longe demais - {season}...")
            ftp = ftplib.FTP(FTP_HOST, timeout=15)
            ftp.login(FTP_USER, FTP_PASS)
            ftp.cwd(f"/G/Series/Longe demais - {season}")
            try:
                tmp_path = en_srt.with_suffix(".tmp")
                with open(tmp_path, "wb") as fp:
                    ftp.retrbinary(f"RETR {stem}.en.srt", fp.write)
                tmp_path.replace(en_srt)
                print(f"[OK] Baixado do FTP: {en_srt}")
            except ftplib.error_perm as exc:
                if tmp_path.exists():
                    tmp_path.unlink()
                ftp.quit()
                print(f"[AVISO] {stem}.en.srt não está no FTP ({exc}). Buscando automaticamente no SubtitleCat...")
                fetched = fetch_en_srt_subtitlecat(ep)
                if not fetched:
                    sys.exit(f"Erro: {stem}.en.srt não encontrado no FTP nem no SubtitleCat.")
                clean_text, src_path, blk_count, quality = fetched
                en_srt.write_text(clean_text, encoding="utf-8")
                print(f"[WEB] Baixado do SubtitleCat: {src_path} ({blk_count} blocos, tipo={quality})")
                try:
                    ftp_up = ftplib.FTP(FTP_HOST, timeout=15)
                    ftp_up.login(FTP_USER, FTP_PASS)
                    ftp_up.cwd(f"/G/Series/Longe demais - {season}")
                    with open(en_srt, "rb") as fp:
                        ftp_up.storbinary(f"STOR {stem}.en.srt", fp)
                    ftp_up.quit()
                    print(f"[FTP] Backup de {stem}.en.srt salvo no FTP.")
                except Exception as up_exc:
                    print(f"[AVISO] Não foi possível salvar backup no FTP: {up_exc}")
            else:
                ftp.quit()

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


def sanitize_cue_text(text: str) -> str:
    r"""Normaliza quebras de linha (\N, ' / ') e travessões longos (—) vindos de revisões automáticas."""
    # Converte \N (sintaxe ASS) em quebra de linha real de SRT
    text = text.replace(r"\N", "\n")
    # Converte separador visual ' / ' copiado de review_chunk*.txt em quebra de linha real
    text = re.sub(r"\s+/\s+", "\n", text)
    # Normaliza travessão longo (—) em hífen padrão (- )
    text = re.sub(r"(?m)^—\s*", "- ", text)
    text = re.sub(r"\s+—\s+", "\n- ", text)
    # Remove linhas vazias extras dentro do mesmo bloco
    clean_lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(clean_lines)


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
    sanitized_count = 0
    for cid in range(1, 5):
        pt_p = work / f"chunk{cid}.pt-BR.srt"
        if not pt_p.exists():
            continue
        for b in [x.strip() for x in pt_p.read_text(encoding="utf-8-sig").strip().split("\n\n") if x.strip()]:
            lines = b.splitlines()
            idx = int(lines[0])
            timing = lines[1]
            raw_text = all_fixes[idx] if idx in all_fixes else "\n".join(lines[2:])
            clean_text = sanitize_cue_text(raw_text)
            if clean_text != raw_text.strip():
                sanitized_count += 1
            final_blocks.append(f"{idx}\n{timing}\n{clean_text}")

    if len(final_blocks) != total_expected:
        sys.exit(f"Erro de paridade: final={len(final_blocks)} != original={total_expected}")

    com_orador = work / f"{stem}.com_orador.pt-BR.srt"
    com_orador.write_text("\n\n".join(final_blocks) + "\n", encoding="utf-8")
    print(f"[OK] Mesclados {len(final_blocks)} blocos ({len(all_fixes)} correções QA | {sanitized_count} blocos sanitizados).")

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

    # 3. Fire TV: tenta ADB direto local (192.168.0.218:5555) primeiro; fallback para ssh a70
    firetv_addr = "192.168.0.218:5555"
    pushed_direct = False
    if shutil.which("adb"):
        subprocess.run(["adb", "connect", firetv_addr], capture_output=True, text=True, timeout=8)
        local_devs = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=5).stdout
        if f"{firetv_addr}\tdevice" in local_devs:
            ok_cnt = 0
            for f in deliverables:
                r1 = subprocess.run(["adb", "-s", firetv_addr, "push", str(f), "/sdcard/Download/"], capture_output=True, text=True)
                r2 = subprocess.run(["adb", "-s", firetv_addr, "push", str(f), "/sdcard/Android/data/org.courville.nova/cache/subtitles/"], capture_output=True, text=True)
                if r1.returncode == 0 and r2.returncode == 0:
                    ok_cnt += 1
            print(f"[FIRE TV] {ok_cnt}/4 arquivos enviados diretamente via ADB local ({firetv_addr}) -> Download + Nova cache")
            pushed_direct = ok_cnt == len(deliverables)

    if not pushed_direct:
        tmp_a70 = f"/data/data/com.termux/files/home/tmp_ep{ep}_push"
        subprocess.run(["ssh", "a70", f"mkdir -p {tmp_a70}"], check=True)
        for f in deliverables:
            subprocess.run(["scp", "-q", str(f), f"a70:{tmp_a70}/{f.name}"], check=True)
        devs = subprocess.run(["ssh", "a70", "adb devices"], capture_output=True, text=True).stdout
        target_dev = "emulator-5554" if "emulator-5554\tdevice" in devs else firetv_addr
        ok_cnt = 0
        for f in deliverables:
            r1 = subprocess.run(["ssh", "a70", f"adb -s {target_dev} push {tmp_a70}/{f.name} /sdcard/Download/"], capture_output=True, text=True)
            r2 = subprocess.run(["ssh", "a70", f"adb -s {target_dev} push {tmp_a70}/{f.name} /sdcard/Android/data/org.courville.nova/cache/subtitles/"], capture_output=True, text=True)
            if r1.returncode == 0 and r2.returncode == 0:
                ok_cnt += 1
        subprocess.run(["ssh", "a70", f"rm -rf {tmp_a70}"], check=True)
        print(f"[FIRE TV] {ok_cnt}/4 arquivos enviados via A70 ({target_dev}) -> Download + Nova cache")


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
