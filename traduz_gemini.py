#!/usr/bin/env python3
"""
Traduz arquivos .srt (ex: Turco -> Português do Brasil) usando a API do Google Gemini
com janela de contexto deslizante, autodetecção do modelo Flash mais recente ativo na conta,
rotação automática entre modelos Flash caso atinja cota gratuita (HTTP 429)
e retomada automática (checkpoint).
"""
import argparse
import getpass
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://generativelanguage.googleapis.com/v1beta"

SYSTEM_PROMPT = """Você é um tradutor sênior de legendas de séries dramáticas turcas (dizis) para o Português do Brasil (PT-BR), especializado na série "Uzak Şehir" (Longe Demais), ambientada em Mardin.

PERSONAGENS E DINÂMICAS:
- Família Albora:
  * Cihan Albora: Líder patriarcal forte, protetor e honrado. Fala com autoridade e respeito.
  * Alya Albora: Médica pediatra canadense, mãe de Deniz e esposa de Boran. No início da história, vai a Mardin para o funeral do marido dado como morto.
  * Boran Albora: Marido de Alya, dado como morto e depois encontrado vivo em estado crítico, vegetativo e em coma. Após essa revelação, não o descreva como falecido; não antecipe a revelação em cenas anteriores.
  * Sadakat Albora (Sadakat Hanım): Matriarca implacável e tradicional. Chame de "Dona Sadakat" ou "Senhora Sadakat".
  * Kaya Albora: Irmão mais novo leal a Cihan, noivo de İpek.
  * İpek: Noiva de Kaya.
  * Şahin Albora: Primo impulsivo e explosivo (filho de Ecmel).
  * Nare Albora: Irmã de Cihan.
  * Deniz: Filho de Alya e Boran; ajuste a voz infantil à idade aparente e ao momento da história, sem fixar idade não confirmada.
  * Kadir, Muzaffer: Homens de confiança da mansão.
- Clã Baybars (Inimigos mortais):
  * Demir Baybars: Rival violento e implacável.
  * Ecmel: Traidor.

RELAÇÕES DE PARENTESCO E ARMADILHAS DO TURCO (CRUCIAL):
- "Gelin" / "Gelinim":
  * Em turco significa tanto "noiva" quanto "NORA"!
  * Use "nora" quando a relação de sogra/família do noivo estiver confirmada; em outros casos, decida entre "nora" e "noiva" pelo contexto.
  * Se o próprio noivo falar, "noiva" pode ser adequado antes do casamento; considere a cena e o momento da trama.
- "Damat" / "Damadım":
  * Se dita pelos sogros/família: "GENRO" ou "nosso genro".
  * Se dita pela noiva: "meu noivo".
- "Anne diyeceksin bana": "Vai me chamar de mãe!" (a sogra tradicional turca exige que a nora a chame de mãe).

TRATAMENTOS CULTURAIS E VOCABULÁRIO:
- "Yenge" -> "Cunhada" (ou "Dona Alya" dependendo do respeito do capataz).
- "Abi" -> "Irmão" / "Meu irmão".
- "Abla" -> "Irmã".
- "Ağa" -> "Agha" ou "Patrão".
- "Konak / Konağın" -> "Mansão" / "Casa dos Albora".
- "Başım üstüne" -> "Às suas ordens" / "Com certeza".
- "Allah aşkına" -> "Pelo amor de Deus".
- "Geçmiş olsun" -> "Que passe logo" / "Melhoras".

CORREÇÃO DE ALUCINAÇÕES FONÉTICAS DO WHISPER NO TURCO:
- O áudio turco gravado com vento ou música tem erros fonéticos comuns:
  * "telsiz" pode referir-se a rádio/comunicador; confirme pela cena antes de corrigir uma transcrição incerta.
  * "Ali Hanım" pode ser uma referência a Alya; confirme pelo contexto.
  * "Hamada" pode ser o personagem Hamada; não o confunda com Alya sem evidência.
  * "Zerrin" é a filha de Ecmel e Fidan e irmã de Şahin; preserve o nome próprio.
  * Menções a Mardin podem ser nomes ou parte de uma canção; use o contexto.

REGRAS DE LEGENDA:
1. Português do Brasil coloquial dramático, sonoro e natural (como em dublagem/legendagem profissional de streaming).
2. TRADUÇÃO: Traduza diálogos comuns para PT-BR, preservando nomes próprios e trechos deliberadamente mantidos no original.
3. GÊNERO: Sadakat e Zerrin são mulheres; use formas femininas quando forem o referente confirmado. Como o pronome turco não marca gênero, use a cena para identificar o referente e não adivinhe quando houver dúvida.
4. PARENTESCO: Use a relação familiar confirmada pela cena e pelo ponto da trama; não atribua parentesco sem evidência.
5. ORADOR: Não acrescente nomes às falas. Se a entrada exigir etiquetas, use-as somente quando a identidade do falante estiver confiavelmente estabelecida; nunca deduza apenas pelo texto.
6. CONTEXTO: Não confunda Deniz, o menino, com Cihan, o adulto. Ajuste vocativos afetivos e familiares a quem fala e à relação confirmada, sem aplicar equivalências rígidas.
7. Respeite pontuação de suspense, exclamações e quebras de frase úteis.
8. Não resuma nem invente fatos fora do contexto; apenas traduza com exatidão e naturalidade.
9. Responda EXCLUSIVAMENTE em formato JSON:
   [{"id": <numero>, "text": "<tradução em PT-BR>"}]"""

def carregar_prompt_sistema() -> str:
    """Carrega as diretrizes completas da skill dizi-translator se o arquivo existir, combinando com o prompt base."""
    skill_paths = [
        Path(__file__).resolve().parent / ".agents/skills/dizi-translator/SKILL.md",
        Path.home() / ".agents/skills/dizi-translator/SKILL.md",
    ]
    for sp in skill_paths:
        if sp.is_file():
            try:
                conteudo = sp.read_text(encoding="utf-8")
                conteudo = re.sub(r"^---\s*\n.*?\n---\s*\n", "", conteudo, flags=re.DOTALL).strip()
                print(f"==> Skill dizi-translator incorporada ao prompt a partir de: {sp}", flush=True)
                return f"{SYSTEM_PROMPT}\n\n--- DIRETRIZES DA SKILL DIZI-TRANSLATOR ---\n{conteudo}"
            except Exception as e:
                print(f"Aviso ao carregar skill ({sp}): {e}", file=sys.stderr)
    return SYSTEM_PROMPT

PROMPT_SISTEMA_COMPLETO = carregar_prompt_sistema()


def listar_modelos_flash(api_key: str) -> list[str]:
    """Consulta a API do Gemini para descobrir os modelos Flash ativos na conta em ordem de preferência."""
    url = f"{API_BASE}/models?key={api_key}"
    req = urllib.request.Request(url, headers={"User-Agent": "Termux-SRT-Gemini/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"Erro ao validar chave Gemini (HTTP {e.code}): {detalhe}") from e

    disponiveis = []
    for m in data.get("models", []):
        metodos = m.get("supportedGenerationMethods", [])
        if "generateContent" not in metodos:
            continue
        nome = m.get("name", "").replace("models/", "")
        if any(x in nome for x in ("tts", "image", "vision", "embedding", "aqa", "bison", "learnlm", "omni", "audio", "live", "realtime")):
            continue
        disponiveis.append(nome)

    preferidos = [
        "gemini-3.0-flash",
        "gemini-3-flash-preview",
        "gemini-3-flash",
        "gemini-flash-latest",
    ]
    # Remove estritamente qualquer menção a 2.5 e modelos lite ou omni
    disponiveis = [m for m in disponiveis if "2.5" not in m and "lite" not in m and "omni" not in m]
    ordenados = [p for p in preferidos if p in disponiveis]
    for m in sorted(disponiveis, reverse=True):
        if "flash" in m and "lite" not in m and "omni" not in m and m not in ordenados:
            ordenados.append(m)

    if not ordenados and disponiveis:
        ordenados = disponiveis[:3]

    if not ordenados:
        raise RuntimeError("Nenhum modelo compatível com generateContent encontrado para esta chave.")
    return ordenados


def format_progress_bar(current: int, total: int, width: int = 25) -> str:
    filled = int(width * current / total) if total > 0 else 0
    return "=" * filled + ">" * (1 if filled < width else 0) + "." * max(0, width - filled - 1)


def parse_srt(conteudo: str):
    blocos = re.split(r"\r?\n\s*\r?\n", conteudo.strip())
    itens = []
    for bloco in blocos:
        linhas = [l.rstrip("\r") for l in bloco.splitlines()]
        if len(linhas) >= 3 and "-->" in linhas[1]:
            itens.append({
                "idx": linhas[0].strip(),
                "tempo": linhas[1].strip(),
                "texto": "\n".join(linhas[2:]).strip(),
            })
    return itens


def traduzir_lote(api_key: str, modelo: str, contexto_anterior: list, lote_atual: list) -> dict:
    prompt_partes = []
    if contexto_anterior:
        ctx_json = json.dumps(
            [{"id": item["id"], "tr": item["texto"], "pt": item.get("traducao", "")} for item in contexto_anterior],
            ensure_ascii=False,
        )
        prompt_partes.append(f"CONTEXTO ANTERIOR (apenas referência, NÃO inclua na saída):\n{ctx_json}\n")

    entrada_json = json.dumps(
        [{"id": item["id"], "text": item["texto"]} for item in lote_atual],
        ensure_ascii=False,
    )
    prompt_partes.append(
        f"TRADUZA ESTE LOTE ({len(lote_atual)} itens) PARA PORTUGUÊS DO BRASIL (PT-BR):\n{entrada_json}"
    )

    gen_config = {
        "temperature": 0.2,
        "responseMimeType": "application/json",
    }

    payload = {
        "systemInstruction": {"parts": [{"text": PROMPT_SISTEMA_COMPLETO}]},
        "contents": [{"role": "user", "parts": [{"text": "\n".join(prompt_partes)}]}],
        "generationConfig": gen_config,
    }

    url = f"{API_BASE}/models/{modelo}:generateContent?key={api_key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Termux-SRT-Gemini/1.0"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        corpo = json.loads(resp.read().decode("utf-8"))

    candidatos = corpo.get("candidates", [])
    if not candidatos:
        raise RuntimeError(f"Resposta sem candidatos do Gemini: {corpo}")

    partes = candidatos[0].get("content", {}).get("parts", [])
    texto_resp = ""
    for p in partes:
        if "text" in p and not p.get("thought", False):
            texto_resp = p["text"].strip()
    if not texto_resp and partes:
        texto_resp = partes[-1].get("text", "").strip()

    if texto_resp.startswith("```"):
        texto_resp = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto_resp, flags=re.DOTALL).strip()

    try:
        lista_traduzida = json.loads(texto_resp, strict=False)
    except Exception:
        limpo = re.sub(r'[\x00-\x1f\x7f-\x9f]', lambda m: ' ' if m.group() in '\r\n\t' else '', texto_resp)
        lista_traduzida = json.loads(limpo, strict=False)
    if not isinstance(lista_traduzida, list):
        raise ValueError("O modelo não retornou uma lista JSON.")

    mapa = {}
    for obj in lista_traduzida:
        if isinstance(obj, dict) and "id" in obj and "text" in obj:
            mapa[int(obj["id"])] = str(obj["text"]).strip()

    faltando = [item["id"] for item in lote_atual if item["id"] not in mapa]
    if len(faltando) > len(lote_atual) * 0.15:
        raise ValueError(f"O modelo omitiu {len(faltando)} itens do lote.")

    return mapa


def main():
    parser = argparse.ArgumentParser(description="Traduz legenda .srt usando Google Gemini com janela de contexto.")
    parser.add_argument("entrada", help="Arquivo .srt de entrada")
    parser.add_argument("saida", nargs="?", help="Arquivo .srt de saída (padrão: <entrada>.pt-BR.srt)")
    parser.add_argument("-m", "--model", default="auto", help="Modelo Gemini (padrão: auto - detecta o Flash mais novo)")
    parser.add_argument("-b", "--batch-size", type=int, default=80, help="Falas por lote (padrão: 80)")
    args = parser.parse_args()

    entrada = Path(args.entrada).expanduser()
    if not entrada.is_file():
        print(f"Erro: Arquivo não encontrado: {entrada}", file=sys.stderr)
        sys.exit(1)

    if args.saida:
        saida = Path(args.saida).expanduser()
    else:
        saida = entrada.with_name(f"{entrada.stem}.pt-BR.srt")

    raw_keys = (
        os.environ.get("GEMINI_TRANSLATE_KEYS")
        or os.environ.get("GEMINI_TRANSLATE_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or getpass.getpass("Cole sua GEMINI_TRANSLATE_KEY (não aparecerá na tela): ")
    )
    # Suporta múltiplas chaves separadas por vírgula, ponto-e-vírgula ou nova linha
    api_keys = [k.strip() for k in re.split(r"[,;\n]+", raw_keys) if k.strip()]
    if not api_keys:
        print("Erro: É necessária ao menos uma GEMINI_TRANSLATE_KEY (obtenha em https://aistudio.google.com/apikey).", file=sys.stderr)
        sys.exit(1)

    key_index = 0
    api_key = api_keys[key_index]
    if len(api_keys) > 1:
        print(f"==> Pool de chaves Gemini ativado com {len(api_keys)} chaves para rotação automática.", flush=True)

    if args.model == "auto":
        print("==> Consultando modelos disponíveis na sua conta Gemini...", flush=True)
        modelos_disponiveis = listar_modelos_flash(api_key)
    else:
        modelos_disponiveis = [args.model]

    idx_modelo = 0
    modelo = modelos_disponiveis[idx_modelo]
    print(f"==> Modelo principal selecionado: {modelo} (alternativas de fallback: {modelos_disponiveis[1:4]})", flush=True)

    dados = entrada.read_bytes()
    conteudo = dados.decode("utf-16") if dados.startswith((b"\xff\xfe", b"\xfe\xff")) else dados.decode("utf-8-sig", errors="replace")
    itens = parse_srt(conteudo)
    for i, item in enumerate(itens, start=1):
        item["id"] = i

    print(f"==> Total de falas para traduzir: {len(itens)}", flush=True)

    ckpt_path = saida.with_suffix(".ckpt.json")
    traducoes_salvas = {}
    if ckpt_path.is_file():
        try:
            traducoes_salvas = {int(k): v for k, v in json.loads(ckpt_path.read_text(encoding="utf-8")).items()}
            print(f"==> Retomando progresso anterior: {len(traducoes_salvas)}/{len(itens)} falas já traduzidas.", flush=True)
        except Exception:
            traducoes_salvas = {}

    for item in itens:
        if item["id"] in traducoes_salvas:
            item["traducao"] = traducoes_salvas[item["id"]]

    batch_size = args.batch_size
    if batch_size <= 0:
        raise ValueError("O tamanho do lote precisa ser maior que zero.")
    total_lotes = (len(itens) + batch_size - 1) // batch_size

    t_inicio = time.time()

    for idx_lote in range(total_lotes):
        inicio = idx_lote * batch_size
        fim = min(inicio + batch_size, len(itens))
        lote_atual = itens[inicio:fim]

        if all("traducao" in item for item in lote_atual):
            continue

        ctx_inicio = max(0, inicio - 8)
        contexto_anterior = itens[ctx_inicio:inicio]

        print(f"\n--> Processando Lote {idx_lote + 1}/{total_lotes} ({len(lote_atual)} falas: #{inicio + 1} a #{fim})...", flush=True)

        for tentativa in range(10):
            try:
                t_lote_start = time.time()
                mapa = traduzir_lote(api_key, modelo, contexto_anterior, lote_atual)
                faltantes = [item["id"] for item in lote_atual if not mapa.get(item["id"])]
                if faltantes:
                    raise ValueError(f"A resposta omitiu {len(faltantes)} falas do lote.")
                t_lote_dur = time.time() - t_lote_start
                for item in lote_atual:
                    texto_trad = mapa.get(item["id"], item["texto"])
                    item["traducao"] = texto_trad
                    traducoes_salvas[item["id"]] = texto_trad
                ckpt_path.write_text(json.dumps(traducoes_salvas, ensure_ascii=False), encoding="utf-8")

                tempo_decorrido = time.time() - t_inicio
                pct_concluido = (fim / len(itens)) * 100
                velocidade = fim / tempo_decorrido if tempo_decorrido > 0 else 0
                falas_restantes = len(itens) - fim
                tempo_restante = falas_restantes / velocidade if velocidade > 0 else 0

                el_m, el_s = divmod(int(tempo_decorrido), 60)
                eta_m, eta_s = divmod(int(tempo_restante), 60)
                bar = format_progress_bar(fim, len(itens), width=20)

                print(
                    f"✓ [{pct_concluido:5.1f}%] [{bar}] Lote {idx_lote + 1}/{total_lotes} OK ({t_lote_dur:.1f}s) | "
                    f"Concluídas: {fim}/{len(itens)} | Tempo: {el_m:02d}:{el_s:02d} | ETA: {eta_m:02d}:{eta_s:02d} ({velocidade:.1f} falas/s)",
                    flush=True,
                )
                # Espaçamento de 4.2s para manter a taxa abaixo de 15 RPM (cota gratuita do Google AI Studio)
                time.sleep(4.2)
                modelo = modelos_disponiveis[0]
                break
            except urllib.error.HTTPError as e:
                detalhe = e.read().decode("utf-8", "replace")[:300]
                if e.code in (429, 500, 502, 503, 504) and tentativa < 9:
                    espera = 25 + (tentativa * 10)
                    # Só cota negada justifica trocar a chave; chaves do mesmo projeto podem compartilhar a cota.
                    # O backoff progressivo continua ativo para não martelar uma cota compartilhada ou um serviço indisponível.
                    if e.code == 429 and len(api_keys) > 1:
                        key_index = (key_index + 1) % len(api_keys)
                        api_key = api_keys[key_index]
                        print(f"Instabilidade/Cota (HTTP {e.code}). Alternando para chave #{key_index + 1}/{len(api_keys)} do pool...", file=sys.stderr, flush=True)

                    # 2. Rotaciona modelo se aplicável
                    modelo_antigo = modelo
                    if len(modelos_disponiveis) > 1:
                        idx_atual = modelos_disponiveis.index(modelo) if modelo in modelos_disponiveis else 0
                        modelo = modelos_disponiveis[(idx_atual + 1) % len(modelos_disponiveis)]
                        print(f"Rotacionando de '{modelo_antigo}' para '{modelo}' e aguardando {espera}s...", file=sys.stderr, flush=True)
                    else:
                        print(f"Aguardando {espera}s para recuperação...", file=sys.stderr, flush=True)
                    time.sleep(espera)
                elif tentativa < 9:
                    espera = 10 * (tentativa + 1)
                    print(f"Erro HTTP {e.code} no lote {idx_lote + 1}. Nova tentativa em {espera}s...", file=sys.stderr, flush=True)
                    time.sleep(espera)
                else:
                    raise RuntimeError(f"Falha definitiva no lote {idx_lote + 1} após 10 tentativas: HTTP {e.code} - {detalhe}")
            except Exception as e:
                if tentativa < 9:
                    espera = 8 * (tentativa + 1)
                    print(f"Aviso no lote {idx_lote + 1} ({e}). Tentando novamente em {espera}s...", file=sys.stderr, flush=True)
                    modelo = modelos_disponiveis[0]
                    time.sleep(espera)
                else:
                    raise RuntimeError(f"Falha definitiva no lote {idx_lote + 1} após 10 tentativas: {e}")

        if idx_lote + 1 < total_lotes:
            time.sleep(3.5)

    blocos_saida = []
    for item in itens:
        texto_final = item.get("traducao") or item["texto"]
        blocos_saida.append(f"{item['idx']}\n{item['tempo']}\n{texto_final}")

    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text("\n\n".join(blocos_saida) + "\n", encoding="utf-8")
    if ckpt_path.is_file() and len(traducoes_salvas) >= len(itens):
        ckpt_path.unlink()
    print(f"==> Concluído! ({len(traducoes_salvas)}/{len(itens)} traduzidas) Legenda salva em: {saida}", flush=True)


if __name__ == "__main__":
    main()
