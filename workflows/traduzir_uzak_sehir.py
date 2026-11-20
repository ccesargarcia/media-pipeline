"""
Workflow Especializado em 2 Passagens para Tradução de Uzak Şehir (Longe Demais)
Uso via run_workflow:
  Args: {"episode": 47, "season": "Segunda Temporada", "distribute": true}
"""
import ftplib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

ep = int(args["episode"])
season = args.get("season", "Segunda Temporada")
distribute = bool(args.get("distribute", True))

MEDIA_DIR = Path("/data/data/com.termux/files/home/media-pipeline")
WORK_BASE = MEDIA_DIR / "work_uzak_sehir" / f"ep{ep}"
WORK_BASE.mkdir(parents=True, exist_ok=True)

STEM = f"Uzak_Sehir_-_Episode_{ep:02d}"
EN_SRT = WORK_BASE / f"{STEM}.en.srt"

# ==============================================================================
# FASE 1: PREPARAÇÃO & FATIAMENTO COM OVERLAP DE CONTEXTO
# ==============================================================================
phase(f"Fase 1 — Preparação Ep {ep}")

if not EN_SRT.exists():
    candidates = [
        Path(f"/data/data/com.termux/files/home/.gemini/antigravity-cli/brain/{CONVERSATION_ID}/scratch/en_backup/{STEM}.en.srt"),
        MEDIA_DIR / "legendas_prontas" / f"{STEM}.en.srt",
    ]
    found = next((p for p in candidates if p.exists()), None)
    if found:
        shutil.copy2(found, EN_SRT)
        log(f"Legenda oficial copiada de: {found}")
    else:
        log(f"Baixando {STEM}.en.srt do FTP...")
        ftp = ftplib.FTP("192.168.0.1", timeout=15)
        ftp.login("admin", "63274c0954")
        ftp.cwd(f"/G/Series/Longe demais - {season}")
        with open(EN_SRT, "wb") as fp:
            ftp.retrbinary(f"RETR {STEM}.en.srt", fp.write)
        ftp.quit()
        log(f"Baixado do FTP com sucesso: {EN_SRT}")

raw_blocks = [b.strip() for b in EN_SRT.read_text(encoding="utf-8-sig").strip().split("\n\n") if b.strip()]
total_blocks = len(raw_blocks)
chunk_size = math.ceil(total_blocks / 4)
log(f"Total de blocos em {STEM}.en.srt: {total_blocks} (4 chunks de ~{chunk_size} blocos)")

chunks_meta = []
for cid in range(1, 5):
    start_idx = (cid - 1) * chunk_size
    end_idx = min(total_blocks, cid * chunk_size)
    if start_idx >= total_blocks:
        break
    chunk_blocks = raw_blocks[start_idx:end_idx]
    first_id = int(chunk_blocks[0].splitlines()[0])
    last_id = int(chunk_blocks[-1].splitlines()[0])

    chunk_en_path = WORK_BASE / f"chunk{cid}.en.srt"
    chunk_en_path.write_text("\n\n".join(chunk_blocks) + "\n", encoding="utf-8")

    # Compacto com contexto das 5 falas anteriores (para fronteiras de cena)
    compact_lines = []
    if start_idx > 0:
        prev_ctx = raw_blocks[max(0, start_idx - 5):start_idx]
        compact_lines.append("=== CONTEXTO ANTERIOR (APENAS REFERÊNCIA — NÃO TRADUZIR) ===")
        for pb in prev_ctx:
            pl = pb.splitlines()
            compact_lines.append(f"[CTX #{pl[0]}]: {' | '.join(pl[2:])}")
        compact_lines.append("=== INÍCIO DO CHUNK PARA TRADUZIR ===")

    for b in chunk_blocks:
        bl = b.splitlines()
        compact_lines.append(f"{bl[0]}: {' | '.join(bl[2:])}")

    compact_path = WORK_BASE / f"chunk{cid}_compact.txt"
    compact_path.write_text("\n".join(compact_lines) + "\n", encoding="utf-8")

    chunks_meta.append({
        "cid": cid,
        "first_id": first_id,
        "last_id": last_id,
        "count": len(chunk_blocks),
        "en_path": str(chunk_en_path),
        "compact_path": str(compact_path),
        "pt_path": str(WORK_BASE / f"chunk{cid}.pt-BR.srt"),
        "build_path": str(WORK_BASE / f"build_chunk{cid}.py"),
        "review_path": str(WORK_BASE / f"review_chunk{cid}.txt"),
        "fixes_path": str(WORK_BASE / f"fixes_chunk{cid}.json"),
    })

# ==============================================================================
# FASE 2: TRADUÇÃO PARALELA (4x uzak-sehir-translator)
# ==============================================================================
phase(f"Fase 2 — Tradução Paralela Ep {ep} (4 agentes)")

translate_schema = {
    "type": "object",
    "properties": {
        "chunk_id": {"type": "integer"},
        "blocks_written": {"type": "integer"},
        "output_path": {"type": "string"},
    },
    "required": ["chunk_id", "blocks_written", "output_path"],
}

def make_translator(m):
    prompt = f"""Traduza o Chunk {m['cid']} (blocos #{m['first_id']} a #{m['last_id']}, total de {m['count']} blocos) de Uzak Şehir Episódio {ep} para PT-BR dramático.

Arquivos de entrada:
- Compacto (com contexto anterior): `{m['compact_path']}`
- SRT original com timestamps: `{m['en_path']}`

Saída obrigatória:
1. Leia `{m['compact_path']}` completamente.
2. Crie o script `{m['build_path']}` contendo o dicionário `translations` com TODOS os {m['count']} blocos (#{m['first_id']} a #{m['last_id']}), usando os timestamps exatos de `{m['en_path']}`, e execute-o para gerar `{m['pt_path']}`.
3. Valide que `{m['pt_path']}` tem exatamente {m['count']} blocos sem nenhum ID faltando.
4. Retorne o JSON no finish."""
    return agent(
        prompt=prompt,
        schema=translate_schema,
        role=f"Ep{ep} Tradutor Chunk {m['cid']}",
        type_name="uzak-sehir-translator",
    )

trans_results = await parallel(chunks_meta, make_translator)
log(f"Tradução concluída: {trans_results}")

# ==============================================================================
# FASE 3: REVISÃO PARALELA DE GÊNERO & PRECISÃO (4x uzak-sehir-reviewer)
# ==============================================================================
phase(f"Fase 3 — Auditoria QA de Gênero & Sentido Ep {ep} (4 revisores)")

for m in chunks_meta:
    en_blks = [b.strip() for b in Path(m["en_path"]).read_text(encoding="utf-8-sig").strip().split("\n\n") if b.strip()]
    pt_blks = [b.strip() for b in Path(m["pt_path"]).read_text(encoding="utf-8-sig").strip().split("\n\n") if b.strip()]
    assert len(en_blks) == len(pt_blks), f"Chunk {m['cid']}: EN={len(en_blks)} != PT={len(pt_blks)}"

    rev_lines = []
    for eb, pb in zip(en_blks, pt_blks):
        el = eb.splitlines()
        pl = pb.splitlines()
        rev_lines.append(f"#{el[0]}\nEN: {' / '.join(el[2:])}\nPT: {' / '.join(pl[2:])}")
    Path(m["review_path"]).write_text("\n".join(rev_lines) + "\n", encoding="utf-8")

review_schema = {
    "type": "object",
    "properties": {
        "chunk_id": {"type": "integer"},
        "fixes_count": {"type": "integer"},
        "summary": {"type": "string"},
    },
    "required": ["chunk_id", "fixes_count", "summary"],
}

def make_reviewer(m):
    prompt = f"""Faça a revisão minuciosa cena a cena do Chunk {m['cid']} (blocos #{m['first_id']} a #{m['last_id']}) de Uzak Şehir Episódio {ep}.

Leia integralmente `{m['review_path']}` (EN e PT lado a lado), rastreie [Falante -> Ouvinte] em cada cena e corrija TODO erro de gênero, vocativo invertido (annem/babaannem), parentesco, sentido ou naturalidade PT-BR.

Salve o JSON apenas com os blocos corrigidos em `{m['fixes_path']}` (formato `{{"123": "Linha 1\\nLinha 2"}}`; se não houver erros, salve `{{}}`).
Retorne o resumo no finish."""
    return agent(
        prompt=prompt,
        schema=review_schema,
        role=f"Ep{ep} Revisor QA Chunk {m['cid']}",
        type_name="uzak-sehir-reviewer",
    )

rev_results = await parallel(chunks_meta, make_reviewer)
log(f"Revisão QA concluída: {rev_results}")

# ==============================================================================
# FASE 4: CONSOLIDAÇÃO, LINTER, GERAÇÃO .ASS E DISTRIBUIÇÃO
# ==============================================================================
phase(f"Fase 4 — Consolidação, Linter e Entrega Ep {ep}")

all_fixes = {}
for m in chunks_meta:
    fp = Path(m["fixes_path"])
    if fp.exists():
        data = json.loads(fp.read_text(encoding="utf-8"))
        for k, v in data.items():
            all_fixes[int(k)] = v.strip()

final_blocks = []
for m in chunks_meta:
    pt_blks = [b.strip() for b in Path(m["pt_path"]).read_text(encoding="utf-8-sig").strip().split("\n\n") if b.strip()]
    for b in pt_blks:
        lines = b.splitlines()
        idx = int(lines[0])
        timing = lines[1]
        if idx in all_fixes:
            final_blocks.append(f"{idx}\n{timing}\n{all_fixes[idx]}")
        else:
            final_blocks.append(b)

assert len(final_blocks) == total_blocks, f"Final {len(final_blocks)} != Original {total_blocks}"

COM_ORADOR_SRT = WORK_BASE / f"{STEM}.com_orador.pt-BR.srt"
COM_ORADOR_SRT.write_text("\n\n".join(final_blocks) + "\n", encoding="utf-8")
log(f"Mesclados {len(final_blocks)} blocos com {len(all_fixes)} correções do Revisor QA.")

subprocess.run(
    ["python3", str(MEDIA_DIR / "gerar_versoes_legendas.py"), str(COM_ORADOR_SRT), STEM, str(WORK_BASE)],
    check=True,
)

PT_SRT = WORK_BASE / f"{STEM}.pt-BR.srt"
lint_out = subprocess.run(
    ["python3", str(MEDIA_DIR / "lint_legendas.py"), "-o", str(EN_SRT), "--json", str(PT_SRT)],
    capture_output=True,
    text=True,
    check=True,
)
lint_json = json.loads(lint_out.stdout)
log(f"Linter: valido={lint_json['valido']} | falas={lint_json['total_falas']} | erros={len(lint_json['erros'])} | inconsistencias={len(lint_json['inconsistencias_regras'])}")
assert lint_json["valido"] and len(lint_json["erros"]) == 0, f"Linter falhou: {lint_json['erros']}"

deliverables = [
    WORK_BASE / f"{STEM}.pt-BR.srt",
    WORK_BASE / f"{STEM}.ass",
    WORK_BASE / f"{STEM}.com_orador.pt-BR.srt",
    WORK_BASE / f"{STEM}.com_orador.ass",
]

if distribute:
    # 1. Local Phone
    local_dir = Path("/sdcard/Download/Longe Demais")
    local_dir.mkdir(parents=True, exist_ok=True)
    for f in deliverables:
        shutil.copy2(f, local_dir / f.name)
    log(f"Copiados 4 arquivos para {local_dir}")

    # 2. FTP
    ftp = ftplib.FTP("192.168.0.1", timeout=20)
    ftp.login("admin", "63274c0954")
    ftp.cwd(f"/G/Series/Longe demais - {season}")
    for f in deliverables:
        with open(f, "rb") as fp:
            ftp.storbinary(f"STOR {f.name}", fp)
    ftp.quit()
    log(f"Upload FTP concluído em /G/Series/Longe demais - {season}")

    # 3. Fire TV via A70 ADB
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
    log(f"Enviado para Fire TV ({target_dev})")

print(json.dumps({
    "episode": ep,
    "total_blocks": total_blocks,
    "qa_fixes_applied": len(all_fixes),
    "lint_valid": lint_json["valido"],
    "lint_errors": len(lint_json["erros"]),
    "work_dir": str(WORK_BASE),
}, ensure_ascii=False, indent=2))
