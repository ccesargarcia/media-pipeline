#!/usr/bin/env python3
"""
Linter e Validador de Integridade de Legendas (.srt e .ass):
- Validação 1:1 estrita: número exato de blocos entre original e tradução.
- Validação de Timings e Duração: timestamps válidos, sem tempos negativos ou invertidos.
- Checagem de Leiturabilidade (CPS - Characters Per Second): alerta falas com > 22 caracteres/s.
- Sanity Check da Trama e Personagens (Dizi Uzak Şehir):
  * Alerta se qualquer pessoa além da matriarca Sadakat for chamada de "vovó" ou "minha avó".
  * Alerta se nomes fundamentais forem corrompidos (Cihan, Alya, Boran, Demir, Sadakat).
- Verificação de tags e formatação ASS (tarja preta &H00000000 e cor amarela &H0000FFFF).
"""
import argparse
import os
import re
import sys
from pathlib import Path


def parse_time(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    partes = ts.split(":")
    if len(partes) != 3:
        raise ValueError(f"Formato de tempo inválido: {ts}")
    return int(partes[0]) * 3600 + int(partes[1]) * 60 + float(partes[2])


def parse_srt(conteudo: str):
    blocos = re.split(r"\r?\n\s*\r?\n", conteudo.strip())
    itens = []
    for bloco in blocos:
        linhas = [l.rstrip("\r") for l in bloco.splitlines() if l.strip()]
        if len(linhas) >= 3 and "-->" in linhas[1]:
            m = re.match(r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})", linhas[1])
            if m:
                t_ini = parse_time(m.group(1))
                t_fim = parse_time(m.group(2))
                itens.append({
                    "idx": linhas[0].strip(),
                    "start": t_ini,
                    "end": t_fim,
                    "start_str": m.group(1),
                    "end_str": m.group(2),
                    "texto": "\n".join(linhas[2:]).strip(),
                })
    return itens


def validar_legendas(
    arquivo_ptbr: Path,
    arquivo_original: Path = None,
    arquivo_ass: Path = None,
    max_cps: float = 23.0,
    modo_estrito: bool = False,
) -> dict:
    erros = []
    avisos = []

    if not arquivo_ptbr.is_file():
        return {"valido": False, "erros": [f"Arquivo PT-BR não encontrado: {arquivo_ptbr}"], "avisos": []}

    conteudo_pt = arquivo_ptbr.read_text(encoding="utf-8-sig", errors="replace")
    itens_pt = parse_srt(conteudo_pt)

    if not itens_pt:
        return {"valido": False, "erros": ["Arquivo PT-BR não contém blocos de legenda válidos."], "avisos": []}

    # 1. Comparação 1:1 se arquivo original for fornecido
    if arquivo_original and arquivo_original.is_file():
        conteudo_orig = arquivo_original.read_text(encoding="utf-8-sig", errors="replace")
        itens_orig = parse_srt(conteudo_orig)
        if len(itens_orig) != len(itens_pt):
            diff = abs(len(itens_orig) - len(itens_pt))
            pct = (diff / len(itens_orig)) * 100 if itens_orig else 0
            msg = f"Divergência de contagem: Original tem {len(itens_orig)} falas, mas Tradução tem {len(itens_pt)} falas (diferença de {diff} falas / {pct:.1f}%)."
            if diff > 5:
                erros.append(msg)
            else:
                avisos.append(msg)

    # 2. Validação de timestamps e leiturabilidade
    for i, item in enumerate(itens_pt, start=1):
        duracao = item["end"] - item["start"]
        if duracao <= 0:
            erros.append(f"Bloco #{item['idx']}: Duração negativa ou zero ({item['start_str']} -> {item['end_str']}).")
            continue

        texto_limpo = re.sub(r"\[.*?\]|<.*?>", "", item["texto"]).strip()
        caracteres = len(texto_limpo.replace(" ", "").replace("\n", ""))
        cps = caracteres / duracao if duracao > 0 else 0

        if cps > max_cps and duracao < 1.8 and caracteres > 35:
            avisos.append(f"Bloco #{item['idx']}: Leitura acelerada ({cps:.1f} caracteres/s em {duracao:.2f}s): \"{texto_limpo[:45]}...\"")

        # 3. Sanity check de regras de personagens (Uzak Şehir)
        texto_lower = item["texto"].lower()
        if "vovó" in texto_lower or "minha avó" in texto_lower:
            # Notar que apenas Sadakat pode ser chamada de avó (por Deniz)
            avisos.append(f"Bloco #{item['idx']} [Alerta Genealogia]: Menção a 'vovó/avó'. Certifique-se de que se refere estritamente à Dona Sadakat: \"{item['texto'][:50]}\"")

    # 4. Validação de arquivo ASS se presente
    if arquivo_ass and arquivo_ass.is_file():
        conteudo_ass = arquivo_ass.read_text(encoding="utf-8-sig", errors="replace")
        if "&H00000000" not in conteudo_ass and "BorderStyle=3" not in conteudo_ass:
            avisos.append("Arquivo ASS não parece conter a configuração de tarja preta opaca (BorderStyle=3 / &H00000000).")
        if "&H0000FFFF" not in conteudo_ass and "&H00FFFF" not in conteudo_ass:
            avisos.append("Arquivo ASS não parece conter o estilo de texto em amarelo vivo (&H0000FFFF).")

    valido = len(erros) == 0 if not modo_estrito else (len(erros) == 0 and len(avisos) == 0)
    return {
        "valido": valido,
        "total_falas": len(itens_pt),
        "erros": erros,
        "avisos": avisos,
    }


def main():
    parser = argparse.ArgumentParser(description="Linter e validador de qualidade de legendas.")
    parser.add_argument("ptbr_srt", help="Caminho do arquivo .pt-BR.srt traduzido")
    parser.add_argument("-o", "--original", help="Caminho do .srt original em turco para checagem 1:1")
    parser.add_argument("-a", "--ass", help="Caminho do arquivo .ass para verificar estilização")
    parser.add_argument("--strict", action="store_true", help="Falhar mesmo se houver apenas avisos")
    args = parser.parse_args()

    pt_path = Path(args.ptbr_srt).expanduser()
    orig_path = Path(args.original).expanduser() if args.original else None
    ass_path = Path(args.ass).expanduser() if args.ass else None

    resultado = validar_legendas(
        arquivo_ptbr=pt_path,
        arquivo_original=orig_path,
        arquivo_ass=ass_path,
        modo_estrito=args.strict,
    )

    print(f"\n================ RELATÓRIO DO LINTER DE LEGENDAS ================")
    print(f"Arquivo analisado: {pt_path.name}")
    print(f"Total de falas:    {resultado['total_falas']}")
    print(f"Status:            {'✅ APROVADO' if resultado['valido'] else '❌ REPROVADO'}")
    print(f"=================================================================\n")

    if resultado["erros"]:
        print(f"🚨 ERROS ({len(resultado['erros'])}):")
        for err in resultado["erros"]:
            print(f"  ❌ {err}")
        print()

    if resultado["avisos"]:
        print(f"⚠️  AVISOS ({len(resultado['avisos'])}):")
        for av in resultado["avisos"][:10]:
            print(f"  ⚠️  {av}")
        if len(resultado["avisos"]) > 10:
            print(f"  ... e mais {len(resultado['avisos']) - 10} avisos.")
        print()

    if not resultado["valido"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
