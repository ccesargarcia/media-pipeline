#!/usr/bin/env python3
"""
Linter e Validador de Integridade de Legendas (.srt e .ass):
- Validação 1:1: blocos, IDs, ordem e timestamps milimetricamente iguais ao original.
- Validação de Timings e Duração: timestamps válidos, sem tempos negativos ou invertidos.
- Checagem indicativa de leiturabilidade (CPS - Characters Per Second).
- Verificação de tags e formatação ASS (tarja preta &H00000000 e cor amarela &H0000FFFF).
- Auditoria de Regras Semânticas da Skill (dizi-translator / Uzak Şehir):
  * Alucinações fonéticas do Whisper ("bir sus" -> "um pássaro", "böbrek" -> "pênis", etc.)
  * Desambiguação de personagens (Dr. Burhan vs Boran Albora; Alya vs Ali/Aliye)
  * Expressões regionais traduzidas literalmente ("meu sacrifício", "bem-hallado", etc.)
  * Vocativo materno invertido ("annem" -> "minha mãe")
  * Créditos e vazamentos do Whisper ASR
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

# Regras semânticas baseadas no SKILL.md de dizi-translator (Uzak Şehir)
REGRAS_SKILL = [
    {
        "id": "ASR_PASSARO",
        "nome": "Alucinação Fonética de 'Bir sus!' (Um pássaro)",
        "padrao": re.compile(r"\b(um|o)\s+p[áa]ssar(o|inho)s?\b", re.IGNORECASE),
        "sugestao": "Em cenas tensas/discussões, 'Bir sus!' significa 'Cala a boca! / Fica quieto!'. NUNCA use pássaros em brigas.",
        "severidade": "aviso",
    },
    {
        "id": "ORGAO_ANATOMICO",
        "nome": "Termo Anatômico Suspeito (böbrek = rim)",
        "padrao": re.compile(r"\bp[êe]nis\b", re.IGNORECASE),
        "sugestao": "Possível alucinação/tradução absurda de 'böbrek' (rim). Verifique se o contexto é hospital/cirurgia.",
        "severidade": "erro",
    },
    {
        "id": "DESAMBIG_BURHAN_BORAN",
        "nome": "Homófono Dr. Burhan vs Boran Albora",
        "padrao": re.compile(r"\b(dr\.?|doutor)\s+boran\b|\bburhan\s+albora\b", re.IGNORECASE),
        "sugestao": "Boran é o paciente/marido de Alya internado. O médico especialista externo é o Dr. Burhan.",
        "severidade": "erro",
    },
    {
        "id": "FALSO_NOME_ALIYE",
        "nome": "Falso Nome 'Aliye' no Núcleo Albora",
        "padrao": re.compile(r"\b(aliye\s+han[ıi]m|cunhada\s+aliye|dona\s+aliye|com\s+a\s+aliye|veio\s+com\s+aliye)\b", re.IGNORECASE),
        "sugestao": "Não existe 'Aliye' na família Albora. Trata-se de Alya Albora (dativo turco Alya'ya alucinado pelo Whisper).",
        "severidade": "erro",
    },
    {
        "id": "FALSO_NOME_ALI_ALYA",
        "nome": "Falso Nome 'Ali' atribuído a Alya",
        "padrao": re.compile(r"\bali,\s*voc[êe]\s+est[áa]\s+com\s+febre|\bali,\s*tire\s+a\s+m[ãa]o|\bali\s+ate[sş]in\s+var\b", re.IGNORECASE),
        "sugestao": "Alucinação do Whisper trocando Alya por Ali em vocativo.",
        "severidade": "erro",
    },
    {
        "id": "TERMO_HAYRIDIR",
        "nome": "Uso de 'Hayrıdır' como nome próprio ou sem tradução",
        "padrao": re.compile(r"\bhayr[ıi]d[ıi]r\b", re.IGNORECASE),
        "sugestao": "'Hayrıdır' significa 'O que houve?' ou 'Algum problema?'. Não é nome próprio nem saudação.",
        "severidade": "aviso",
    },
    {
        "id": "IDIOM_SACRIFICIO",
        "nome": "Tradução Literal de 'Kurban olduğum' (Meu sacrifício)",
        "padrao": re.compile(r"\b(meu|que|dorme,?\s*meu)\s+sacrif[íi]cio\b", re.IGNORECASE),
        "sugestao": "'Kurban' em tom afetivo significa 'meu amor', 'meu querido' ou 'pelo amor de Deus'.",
        "severidade": "aviso",
    },
    {
        "id": "IDIOM_BEM_HALLADO",
        "nome": "Tradução Literal de 'Hoş bulduk' (Bem-hallado)",
        "padrao": re.compile(r"\bbem[- ]hallado\b|\bbem[- ]achado\b", re.IGNORECASE),
        "sugestao": "'Hoş bulduk' é a resposta de cortesia a 'bem-vindo'; deve ser traduzido como 'Obrigado / É um prazer estar aqui'.",
        "severidade": "erro",
    },
    {
        "id": "IDIOM_BURRO",
        "nome": "Tradução Literal de 'Eşek kadar adam'",
        "padrao": re.compile(r"\btamanho\s+de\s+um\s+burro\b", re.IGNORECASE),
        "sugestao": "Expressão para 'homem feito / marmanjo barbado com idade para ter juízo'.",
        "severidade": "aviso",
    },
    {
        "id": "IDIOM_CACADOR",
        "nome": "Tradução Literal de 'Ele avca sığmaz'",
        "padrao": re.compile(r"\brede\s+do\s+ca[çc]ador\b", re.IGNORECASE),
        "sugestao": "Significa 'indomável / rebelde / agitado'.",
        "severidade": "aviso",
    },
    {
        "id": "IDIOM_MEIAS",
        "nome": "Tradução Literal de 'Çorap söküğü'",
        "padrao": re.compile(r"\bmeias?\s+secando\b|\bdesfiar\s+da\s+meia\b", re.IGNORECASE),
        "sugestao": "Significa 'as coisas vão se desenrolar / fluir naturalmente'.",
        "severidade": "aviso",
    },
    {
        "id": "VOCATIVO_MATERNO",
        "nome": "Possível Vocativo Materno Invertido ('Minha mãe')",
        "padrao": re.compile(r"^\s*minha\s+m[ãa]e[!,\.\?]?\s*$", re.IGNORECASE),
        "sugestao": "Se for fala de mãe para filho, 'annem' significa 'meu filho / meu amor', nunca 'minha mãe'.",
        "severidade": "aviso",
    },
    {
        "id": "CREDITOS_WHISPER",
        "nome": "Créditos Espúrios de Legenda / Canal ASR",
        "padrao": re.compile(r"\b(legenda|legendas)\s+m\.?k\.?\b|\binscreva-se\s+no\s+canal\b|\bdeixe\s+o?\s*seu\s+like\b|\btradu[çc][ãa]o:\s*whisper\b", re.IGNORECASE),
        "sugestao": "Alucinação de créditos do Whisper ASR. Remova ou substitua pelo diálogo correspondente.",
        "severidade": "erro",
    },
    {
        "id": "TERMO_TURCO_BRUTO",
        "nome": "Termo Turco comum deixado sem tradução",
        "padrao": re.compile(r"\b(hoş\s*bulduk|hoş\s*geldiniz|teşekkür\s*ederim|afiyet\s*olsun)\b", re.IGNORECASE),
        "sugestao": "Expressão comum em turco que deveria ter sido vertida para Português do Brasil.",
        "severidade": "aviso",
    },
]


def parse_time(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    partes = ts.split(":")
    if len(partes) != 3:
        raise ValueError(f"Formato de tempo inválido: {ts}")
    horas, minutos, segundos = int(partes[0]), int(partes[1]), float(partes[2])
    if horas < 0 or minutos < 0 or segundos < 0 or minutos >= 60 or segundos >= 60:
        raise ValueError(f"Timestamp fora do intervalo: {ts}")
    return horas * 3600 + minutos * 60 + segundos


def parse_ass_time(ts: str) -> float:
    """Converte timestamp ASS (centésimos) em segundos."""
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})\.(\d{2})", ts.strip())
    if not match:
        raise ValueError(f"Timestamp ASS inválido: {ts}")
    horas, minutos, segundos, centesimos = map(int, match.groups())
    if minutos >= 60 or segundos >= 60:
        raise ValueError(f"Timestamp ASS fora do intervalo: {ts}")
    return horas * 3600 + minutos * 60 + segundos + centesimos / 100


def parse_srt(conteudo: str):
    blocos = re.split(r"\r?\n\s*\r?\n", conteudo.strip())
    itens = []
    for numero_bloco, bloco in enumerate(blocos, start=1):
        linhas = [l.rstrip("\r") for l in bloco.splitlines() if l.strip()]
        if not linhas:
            continue
        if len(linhas) < 3:
            raise ValueError(f"Bloco #{numero_bloco} incompleto.")
        if not linhas[0].strip().isdigit():
            raise ValueError(f"ID inválido no bloco #{numero_bloco}: {linhas[0]!r}.")
        m = re.fullmatch(
            r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})",
            linhas[1].strip(),
        )
        if not m:
            raise ValueError(f"Timestamp inválido no bloco #{numero_bloco}: {linhas[1]!r}.")
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
    verificar_regras_skill: bool = True,
    regras_como_erros: bool = False,
) -> dict:
    erros = []
    avisos = []
    inconsistencias_regras = []

    if not arquivo_ptbr.is_file():
        return {
            "valido": False,
            "total_falas": 0,
            "erros": [f"Arquivo PT-BR não encontrado: {arquivo_ptbr}"],
            "avisos": [],
            "inconsistencias_regras": [],
        }

    conteudo_pt = arquivo_ptbr.read_text(encoding="utf-8-sig", errors="replace")
    try:
        itens_pt = parse_srt(conteudo_pt)
    except ValueError as exc:
        return {
            "valido": False,
            "total_falas": 0,
            "erros": [f"SRT PT-BR inválido: {exc}"],
            "avisos": [],
            "inconsistencias_regras": [],
        }

    if not itens_pt:
        return {
            "valido": False,
            "total_falas": 0,
            "erros": ["Arquivo PT-BR não contém blocos de legenda válidos."],
            "avisos": [],
            "inconsistencias_regras": [],
        }

    # 1. Comparação 1:1 se arquivo original for fornecido
    if arquivo_original:
        if not arquivo_original.is_file():
            return {
                "valido": False,
                "total_falas": len(itens_pt),
                "erros": [f"Arquivo original não encontrado: {arquivo_original}"],
                "avisos": [],
                "inconsistencias_regras": [],
            }
        conteudo_orig = arquivo_original.read_text(encoding="utf-8-sig", errors="replace")
        try:
            itens_orig = parse_srt(conteudo_orig)
        except ValueError as exc:
            return {
                "valido": False,
                "total_falas": len(itens_pt),
                "erros": [f"SRT original inválido: {exc}"],
                "avisos": [],
                "inconsistencias_regras": [],
            }
        if len(itens_orig) != len(itens_pt):
            diff = abs(len(itens_orig) - len(itens_pt))
            pct = (diff / len(itens_orig)) * 100 if itens_orig else 0
            msg = f"Divergência de contagem: Original tem {len(itens_orig)} falas, mas Tradução tem {len(itens_pt)} falas (diferença de {diff} falas / {pct:.1f}%)."
            erros.append(msg)
        else:
            for idx, (original, traducao) in enumerate(zip(itens_orig, itens_pt), start=1):
                if original["idx"] != traducao["idx"]:
                    erros.append(
                        f"Bloco #{idx}: ID diferente (original {original['idx']}, tradução {traducao['idx']})."
                    )
                if original["start"] != traducao["start"] or original["end"] != traducao["end"]:
                    erros.append(
                        f"Bloco #{idx} (ID {original['idx']}): timestamps diferentes; "
                        f"original {original['start_str']} --> {original['end_str']}, "
                        f"tradução {traducao['start_str']} --> {traducao['end_str']}."
                    )

    # 2. Validação de timestamps e leiturabilidade (CPS)
    for item in itens_pt:
        duracao = item["end"] - item["start"]
        if duracao <= 0:
            erros.append(f"Bloco #{item['idx']}: Duração negativa ou zero ({item['start_str']} -> {item['end_str']}).")
            continue

        texto_limpo = re.sub(r"\[.*?\]|<.*?>", "", item["texto"]).strip()
        caracteres = len(texto_limpo.replace("\n", ""))
        cps = caracteres / duracao if duracao > 0 else 0

        if cps > max_cps:
            avisos.append(f"Bloco #{item['idx']}: Leitura acelerada ({cps:.1f} caracteres/s em {duracao:.2f}s): \"{texto_limpo[:45]}...\"")

        # 3. Auditoria de Regras Semânticas da Skill (se habilitada)
        if verificar_regras_skill:
            for regra in REGRAS_SKILL:
                match = regra["padrao"].search(item["texto"])
                if match:
                    detalhe = {
                        "idx": item["idx"],
                        "timestamp": f"{item['start_str']} --> {item['end_str']}",
                        "regra_id": regra["id"],
                        "regra_nome": regra["nome"],
                        "severidade": regra["severidade"],
                        "trecho_encontrado": match.group(0),
                        "texto_completo": item["texto"],
                        "sugestao": regra["sugestao"],
                    }
                    inconsistencias_regras.append(detalhe)
                    msg_alerta = (
                        f"Bloco #{item['idx']} [{item['start_str']}]: {regra['nome']} "
                        f"(Trecho: \"{match.group(0)}\") -> {regra['sugestao']}"
                    )
                    if regras_como_erros or (regra["severidade"] == "erro" and modo_estrito):
                        erros.append(msg_alerta)
                    else:
                        avisos.append(msg_alerta)

    ids_pt = [item["idx"] for item in itens_pt]
    if len(ids_pt) != len(set(ids_pt)):
        erros.append("O SRT PT-BR contém IDs de bloco duplicados.")

    # 4. Validação de arquivo ASS se presente
    if arquivo_ass and not arquivo_ass.is_file():
        erros.append(f"Arquivo ASS não encontrado: {arquivo_ass}")
    elif arquivo_ass:
        conteudo_ass = arquivo_ass.read_text(encoding="utf-8-sig", errors="replace")
        linhas_dialogue = [linha for linha in conteudo_ass.splitlines() if linha.startswith("Dialogue:")]
        if len(linhas_dialogue) != len(itens_pt):
            erros.append(f"Contagem ASS/SRT divergente: ASS tem {len(linhas_dialogue)} eventos e SRT tem {len(itens_pt)} blocos.")
        else:
            for idx, (linha, item) in enumerate(zip(linhas_dialogue, itens_pt), start=1):
                campos = linha.split(",", 9)
                if len(campos) != 10 or not campos[0].startswith("Dialogue:"):
                    erros.append(f"Evento ASS #{idx} malformado.")
                    continue
                try:
                    inicio_ass, fim_ass = parse_ass_time(campos[1]), parse_ass_time(campos[2])
                except ValueError as exc:
                    erros.append(f"Evento ASS #{idx}: {exc}")
                    continue
                if abs(inicio_ass - item["start"]) > 0.02 or abs(fim_ass - item["end"]) > 0.02:
                    erros.append(
                        f"Evento ASS #{idx} (ID {item['idx']}): timestamps diferentes do SRT "
                        f"(SRT {item['start_str']} --> {item['end_str']}, ASS {campos[1]} --> {campos[2]})."
                    )
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
        "inconsistencias_regras": inconsistencias_regras,
    }


def gerar_markdown_summary(
    resultado: dict,
    arquivo_ptbr: Path,
    arquivo_original: Path = None,
    arquivo_ass: Path = None,
) -> str:
    status_emoji = "✅ APROVADO" if resultado["valido"] else "❌ REPROVADO"
    if resultado["valido"] and resultado["avisos"]:
        status_emoji = "⚠️ APROVADO COM AVISOS"

    linhas = [
        f"## 📋 Relatório de Quality Gate & Auditoria de Legendas",
        f"",
        f"| Métrica | Detalhe |",
        f"| :--- | :--- |",
        f"| **Arquivo Analisado** | `{arquivo_ptbr.name}` |",
        f"| **Total de Falas** | **{resultado['total_falas']}** |",
        f"| **Comparação 1:1 Original** | `{arquivo_original.name if arquivo_original else 'Não fornecido'}` |",
        f"| **Estilização ASS** | `{arquivo_ass.name if arquivo_ass else 'Não fornecido'}` |",
        f"| **Status Geral** | **{status_emoji}** |",
        f"| **Erros Críticos** | {len(resultado['erros'])} |",
        f"| **Avisos / Alertas** | {len(resultado['avisos'])} |",
        f"",
    ]

    inconsistencias = resultado.get("inconsistencias_regras", [])
    if inconsistencias:
        linhas.append("### 🔍 Inconsistências de Regras da Skill Encontradas")
        linhas.append("")
        linhas.append("| Bloco | Timestamp | Regra / Tipo | Trecho Encontrado | Sugestão / Ação |")
        linhas.append("| :---: | :--- | :--- | :--- | :--- |")
        for inc in inconsistencias[:50]:
            trecho = inc["trecho_encontrado"].replace("|", "\\|")
            linhas.append(
                f"| `{inc['idx']}` | `{inc['timestamp']}` | **{inc['regra_nome']}** | `{trecho}` | {inc['sugestao']} |"
            )
        if len(inconsistencias) > 50:
            linhas.append(f"| ... | ... | ... | ... | *mais {len(inconsistencias) - 50} ocorrências omitidas* |")
        linhas.append("")

    if resultado["erros"]:
        linhas.append("### 🚨 Erros Críticos")
        linhas.append("")
        for err in resultado["erros"]:
            linhas.append(f"- ❌ {err}")
        linhas.append("")

    if resultado["avisos"] and not inconsistencias:
        linhas.append("### ⚠️ Avisos Estruturais / Leiturabilidade")
        linhas.append("")
        for av in resultado["avisos"][:20]:
            linhas.append(f"- ⚠️ {av}")
        if len(resultado["avisos"]) > 20:
            linhas.append(f"- *... e mais {len(resultado['avisos']) - 20} avisos.*")
        linhas.append("")

    return "\n".join(linhas)


def main():
    parser = argparse.ArgumentParser(description="Linter e validador de qualidade e regras de legendas.")
    parser.add_argument("ptbr_srt", help="Caminho do arquivo .pt-BR.srt traduzido")
    parser.add_argument("-o", "--original", help="Caminho do .srt original em turco para checagem 1:1")
    parser.add_argument("-a", "--ass", help="Caminho do arquivo .ass para verificar estilização")
    parser.add_argument("--strict", action="store_true", help="Falhar mesmo se houver apenas avisos")
    parser.add_argument("--skip-skill-rules", action="store_true", help="Pular auditoria de regras semânticas da skill")
    parser.add_argument("--fail-on-skill-rules", action="store_true", help="Fazer com que inconsistências da skill contem como erros críticos")
    parser.add_argument("--warn-only", action="store_true", help="Modo opcional/permissivo: exibe relatório mas sempre sai com código 0")
    parser.add_argument("--summary-markdown", help="Caminho do arquivo para salvar o resumo em Markdown (ex: $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--json", action="store_true", help="Imprimir saída em formato JSON estruturado")
    args = parser.parse_args()

    pt_path = Path(args.ptbr_srt).expanduser()
    orig_path = Path(args.original).expanduser() if args.original else None
    ass_path = Path(args.ass).expanduser() if args.ass else None

    resultado = validar_legendas(
        arquivo_ptbr=pt_path,
        arquivo_original=orig_path,
        arquivo_ass=ass_path,
        modo_estrito=args.strict,
        verificar_regras_skill=not args.skip_skill_rules,
        regras_como_erros=args.fail_on_skill_rules,
    )

    if args.summary_markdown:
        md_text = gerar_markdown_summary(resultado, pt_path, orig_path, ass_path)
        try:
            with open(args.summary_markdown, "a" if Path(args.summary_markdown).exists() else "w", encoding="utf-8") as f:
                f.write(md_text + "\n\n")
        except Exception as exc:
            print(f"⚠️ Aviso: Não foi possível escrever summary em {args.summary_markdown}: {exc}", file=sys.stderr)

    if args.json:
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
        if not resultado["valido"] and not args.warn_only:
            sys.exit(1)
        return

    print(f"\n================ RELATÓRIO DO LINTER DE LEGENDAS ================")
    print(f"Arquivo analisado: {pt_path.name}")
    print(f"Total de falas:    {resultado['total_falas']}")
    status_str = "✅ APROVADO" if resultado["valido"] else "❌ REPROVADO"
    if resultado["valido"] and resultado["avisos"]:
        status_str = "⚠️ APROVADO COM AVISOS"
    print(f"Status:            {status_str}")
    print(f"=================================================================\n")

    if resultado["erros"]:
        print(f"🚨 ERROS ({len(resultado['erros'])}):")
        for err in resultado["erros"]:
            print(f"  ❌ {err}")
        print()

    if resultado["avisos"]:
        print(f"⚠️  AVISOS ({len(resultado['avisos'])}):")
        for av in resultado["avisos"][:15]:
            print(f"  ⚠️  {av}")
        if len(resultado["avisos"]) > 15:
            print(f"  ... e mais {len(resultado['avisos']) - 15} avisos.")
        print()

    if not resultado["valido"] and not args.warn_only:
        sys.exit(1)


if __name__ == "__main__":
    main()
