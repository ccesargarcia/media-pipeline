#!/usr/bin/env python3
"""
Revisão e correção abrangente de todos os episódios traduzidos de Uzak Şehir a partir do 36:
Episódios: 36, 37, 38, 39, 40, 41, 44, 45, 46, 47

1. Corrige o erro sistemático do Whisper de 'Burhan' e 'Bora' para 'Boran'.
2. Corrige linhas em turco que vazaram (ex: Ep 39 falas 3 e 4).
3. Corrige expressões literais (ex: 'Durma, meu sacrifício', 'Meu irmão, que sacrifício', 'Bem-hallado').
4. Corrige créditos falsos ('Legenda M.K.').
5. Corrige gênero de Dona Sadakat ('não gosto dela').
6. Gera arquivos .srt e .ass estilizados (amarelo com tarja preta).
7. Distribui para Fire TV (ADB), Armazenamento Local e FTP do Roteador.
"""
import os
import re
import shutil
import subprocess
import sys
from ftplib import FTP
from pathlib import Path

WORKDIR = Path("/data/data/com.termux/files/home/media-pipeline/audit_episodes")
PIPELINE_DIR = WORKDIR.parent
sys.path.insert(0, str(PIPELINE_DIR))
from gerar_versoes_legendas import srt_to_ass

EPS = [36, 37, 38, 39, 40, 41, 44, 45, 46, 47]

def parse_srt(path: Path):
    content = path.read_text(encoding="utf-8-sig", errors="replace").strip()
    blocks = re.split(r"\r?\n\s*\r?\n", content)
    cues = []
    for b in blocks:
        lines = [l.strip() for l in b.splitlines() if l.strip()]
        if len(lines) >= 3 and "-->" in lines[1]:
            idx = int(lines[0])
            timing = lines[1]
            text = "\n".join(lines[2:])
            cues.append((lines[0], timing, text))
    return cues

def revisar_texto(ep: int, idx: int, texto: str) -> str:
    # 1. Correções pontuais específicas por episódio e ID
    if ep == 39:
        if idx == 1 and re.search(r"legenda\s+m\.k", texto, re.I):
            return "[Música de abertura: Mardin]"
        if idx == 3:
            return "Boran, está me ouvindo?"
        if idx == 4:
            return "Boran, você está me ouvindo?"
        if idx == 295 and "meu sacrifício" in texto.lower():
            return "Durma, meu amor."

    if ep == 38:
        if idx == 1063 and "que sacrifício" in texto.lower():
            return "Meu irmão, pelo amor de Deus! Olha, a turma toda está aqui."

    if ep == 46:
        if idx == 3 and "bem-hallado" in texto.lower():
            return "Muito obrigado, é um prazer estar aqui."

    if ep == 37:
        if idx == 672:
            return texto.replace("não gosto dele", "não gosto dela")

    if ep == 41:
        if idx == 1289 and re.search(r"legenda\s+m\.k", texto, re.I):
            return "[Música de abertura: Mardin]"

    # 2. Correções globais sistemáticas
    # Burhan -> Boran
    texto = re.sub(r"\bBurhan\b", "Boran", texto)
    texto = re.sub(r"\bburhan\b", "Boran", texto)

    # Bora -> Boran (quando se refere a pessoa, não a 'bora lá' ou 'embora')
    texto = re.sub(r"\bBora\b(?!\s+(lá|pra|vamos|aonde|embora))", "Boran", texto)

    # Aliye -> Alya
    texto = re.sub(r"\bAliye Hanım\b", "Dona Alya", texto)
    texto = re.sub(r"\bAliye\b", "Alya", texto)

    # Cihal -> Cihan
    texto = re.sub(r"\bCihal\b", "Cihan", texto)

    # Ecmui -> Ecmel
    texto = re.sub(r"\bEcmui\b", "Ecmel", texto)

    return texto

def processar_episodios():
    print("=== INICIANDO REVISÃO DOS EPISÓDIOS 36 A 47 ===")
    arquivos_prontos = []

    for ep in EPS:
        f_pt = WORKDIR / f"Uzak_Sehir_-_Episode_{ep}.pt-BR.srt"
        if not f_pt.is_file():
            print(f"[!] Episódio {ep}: Arquivo não encontrado: {f_pt.name}")
            continue

        cues = parse_srt(f_pt)
        ajustes = 0
        cues_revisadas = []

        for idx_str, timing, texto in cues:
            idx = int(idx_str)
            novo_texto = revisar_texto(ep, idx, texto)
            if novo_texto != texto:
                ajustes += 1
            cues_revisadas.append((idx_str, timing, novo_texto))

        stem = f"Uzak_Sehir_-_Episode_{ep}"
        out_pt_srt = WORKDIR / f"{stem}.pt-BR.srt"
        out_orador_srt = WORKDIR / f"{stem}.com_orador.pt-BR.srt"
        out_pt_ass = WORKDIR / f"{stem}.ass"
        out_orador_ass = WORKDIR / f"{stem}.com_orador.ass"

        # Escreve .pt-BR.srt
        with open(out_pt_srt, "w", encoding="utf-8") as f:
            for idx_str, timing, text in cues_revisadas:
                f.write(f"{idx_str}\n{timing}\n{text}\n\n")

        # Escreve .com_orador.pt-BR.srt
        with open(out_orador_srt, "w", encoding="utf-8") as f:
            for idx_str, timing, text in cues_revisadas:
                f.write(f"{idx_str}\n{timing}\n{text}\n\n")

        # Gera .ass estilizados
        srt_to_ass(out_pt_srt, out_pt_ass)
        srt_to_ass(out_orador_srt, out_orador_ass)

        print(f"✓ Episódio {ep}: {ajustes} falas corrigidas. Gerados arquivos .srt e .ass")
        arquivos_prontos.extend([out_pt_srt, out_orador_srt, out_pt_ass, out_orador_ass])

    print(f"\n==> Total de arquivos atualizados: {len(arquivos_prontos)}")

    # 1. Copia para Armazenamento Local do Celular
    local_dir = Path("/sdcard/Download/Longe Demais")
    try:
        local_dir.mkdir(parents=True, exist_ok=True)
        for f in arquivos_prontos:
            shutil.copy2(f, local_dir / f.name)
        print(f"✓ {len(arquivos_prontos)} arquivos copiados para o celular: {local_dir}")
    except Exception as e:
        print(f"Aviso ao copiar localmente: {e}")

    # 2. Envia para o Fire TV via ADB
    try:
        subprocess.run(["adb", "connect", "192.168.0.218:5555"], capture_output=True, timeout=5)
        for f in arquivos_prontos:
            subprocess.run(["adb", "-s", "192.168.0.218:5555", "push", str(f), "/sdcard/Download/"], check=True, capture_output=True, timeout=15)
        print(f"✓ {len(arquivos_prontos)} arquivos enviados via ADB para o Fire TV (/sdcard/Download/)")
    except Exception as e:
        print(f"Aviso ao enviar via ADB: {e}")

    # 3. Envia para o FTP do Roteador NAS
    try:
        ftp = FTP()
        ftp.connect("192.168.0.1", 21, timeout=15)
        ftp.login("admin", "63274c0954")
        ftp.cwd("/G/Series/Longe demais - Segunda Temporada")
        for f in arquivos_prontos:
            with open(f, "rb") as fp:
                ftp.storbinary(f"STOR {f.name}", fp)
        ftp.quit()
        print(f"✓ {len(arquivos_prontos)} arquivos atualizados no FTP do Roteador NAS (/G/Series/Longe demais - Segunda Temporada/)")
    except Exception as e:
        print(f"Aviso ao enviar para o FTP: {e}")

    print("\n=== REVISÃO E DISTRIBUIÇÃO CONCLUÍDAS COM SUCESSO ===")

if __name__ == "__main__":
    processar_episodios()
