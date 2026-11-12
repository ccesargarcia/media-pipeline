#!/usr/bin/env python3
"""
Benchmark objetivo de modelos de tradução no Golden Set de Uzak Şehir (22 falas difíceis).
Testa todos os motores com chaves configuradas no ambiente e avalia:
- Latência total
- Paridade 1:1
- Linter oficial (lint_legendas.py)
- Scorecard semântico (10 armadilhas reais dos episódios 35-47)
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BENCH_DIR = Path(__file__).resolve().parent
GOLDEN_SRT = BENCH_DIR / "golden_set.srt"
OUT_DIR = BENCH_DIR / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(BASE_DIR))


def parse_srt(path: Path) -> dict[int, str]:
    content = path.read_text(encoding="utf-8-sig", errors="replace").strip()
    blocks = re.split(r"\r?\n\s*\r?\n", content)
    cues = {}
    for b in blocks:
        lines = [l.strip() for l in b.splitlines() if l.strip()]
        if len(lines) >= 3 and "-->" in lines[1]:
            cues[int(lines[0])] = " ".join(lines[2:]).strip()
    return cues


def avaliar_scorecard(cues: dict[int, str]) -> tuple[int, int, list[str]]:
    """Avalia 10 armadilhas conhecidas de Uzak Şehir. Retorna (pontos, total, falhas)."""
    falhas = []
    pontos = 0
    total = 10

    # 1. Boran preservado na fala #2
    c2 = cues.get(2, "")
    if re.search(r"\bBoran\b", c2) and not re.search(r"\bBora\b", c2):
        pontos += 1
    else:
        falhas.append(f"#2 Boran virou Bora/outro: '{c2}'")

    # 2. Çıkmasın em 3a pessoa (#5)
    c5 = cues.get(5, "").lower()
    if any(w in c5 for w in ["ele", "deixe", "sai"]):
        if "ele" in c5 or "deixe" in c5 or "menino" in c5:
            pontos += 1
        else:
            falhas.append(f"#5 Çıkmasın traduzido sem 3ª pessoa (Deniz): '{cues.get(5, '')}'")
    else:
        falhas.append(f"#5 Çıkmasın inesperado: '{cues.get(5, '')}'")

    # 3. Kurban sem literalismo 'sacrifício' (#6 e #12)
    c6 = cues.get(6, "").lower()
    c12 = cues.get(12, "").lower()
    if "sacrif" not in c6 and "sacrif" not in c12:
        pontos += 1
    else:
        falhas.append(f"#6/#12 Kurban literal ('sacrifício'): #6='{cues.get(6, '')}' | #12='{cues.get(12, '')}'")

    # 4. Aliye corrigido para Alya (#7)
    c7 = cues.get(7, "")
    if re.search(r"\bAlya\b", c7) and not re.search(r"\bAliye\b", c7, re.I):
        pontos += 1
    else:
        falhas.append(f"#7 Manteve Aliye em vez de Alya: '{c7}'")

    # 5. Parlama não traduzido como 'brilhar' (#8)
    c8 = cues.get(8, "").lower()
    if "brilh" not in c8:
        pontos += 1
    else:
        falhas.append(f"#8 Parlama literal ('brilhar'): '{cues.get(8, '')}'")

    # 6. Ecmel e Allah razı olsun (#9)
    c9 = cues.get(9, "")
    if "agradeça" not in c9.lower() and ("ecmel" in c9.lower() or "abençoe" in c9.lower()):
        pontos += 1
    else:
        falhas.append(f"#9 Ecmui/Allah razı olsun literal: '{c9}'")

    # 7. Ayağına sağlık sem 'saúde nos pés' (#13)
    c13 = cues.get(13, "").lower()
    if "pés" not in c13 and "pé" not in c13:
        pontos += 1
    else:
        falhas.append(f"#13 Ayağına sağlık literal ('saúde nos pés'): '{cues.get(13, '')}'")

    # 8. Asana/Maldição (#15 e #16)
    c15 = cues.get(15, "").lower()
    c16 = cues.get(16, "").lower()
    if "asana" not in c15 and "abençoe" not in c16:
        pontos += 1
    else:
        falhas.append(f"#15/#16 Asana/Maldição invertida: #15='{cues.get(15, '')}' | #16='{cues.get(16, '')}'")

    # 9. Cena Sadakat & Alya (#17, #19, #20)
    c17 = cues.get(17, "").lower()
    c19 = cues.get(19, "").lower()
    c20 = cues.get(20, "").lower()
    ok_17 = "juiz" not in c17
    ok_19 = "nora" in c19 and "visita" not in c19
    ok_20 = "sadakat" in c20 and "caridade" not in c20 and "sadaka " not in c20
    if ok_17 and ok_19 and ok_20:
        pontos += 1
    else:
        falhas.append(f"#17/#19/#20 Cena Sadakat/Alya: #17='{cues.get(17, '')}' | #19='{cues.get(19, '')}' | #20='{cues.get(20, '')}'")

    # 10. Hoş bulduk sem 'bem-hallado' (#22)
    c22 = cues.get(22, "").lower()
    if "hallado" not in c22 and "achado" not in c22:
        pontos += 1
    else:
        falhas.append(f"#22 Hoş bulduk literal: '{c22}'")

    return pontos, total, falhas


def rodar_linter(pt_srt: Path) -> tuple[bool, str]:
    res = subprocess.run(
        [sys.executable, str(BASE_DIR / "lint_legendas.py"), str(pt_srt), "-o", str(GOLDEN_SRT)],
        capture_output=True,
        text=True,
    )
    ok = res.returncode == 0
    m = re.search(r"Avisos:\s*(\d+)", res.stdout)
    avisos = m.group(1) if m else "?"
    return ok, f"{'PASS' if ok else 'FAIL'} (avisos={avisos})"


def run_candidate(name: str, cmd: list[str], out_srt: Path, env: dict | None = None) -> dict:
    ckpt = out_srt.with_suffix(".ckpt.json")
    if ckpt.exists():
        ckpt.unlink()
    if out_srt.exists():
        out_srt.unlink()

    t0 = time.time()
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)

    print(f"\n==> Executando benchmark: {name}...", flush=True)
    res = subprocess.run(cmd, cwd=str(BASE_DIR), env=proc_env, capture_output=True, text=True)
    dt = time.time() - t0

    if res.returncode != 0 or not out_srt.is_file():
        err_tail = (res.stderr or res.stdout or "").strip().splitlines()[-5:]
        print(f"  ❌ Falhou ({dt:.1f}s): {' | '.join(err_tail)}", flush=True)
        return {
            "name": name,
            "status": "ERROR",
            "time_s": round(dt, 2),
            "score": "0/10",
            "lint": "N/A",
            "falhas": [" | ".join(err_tail)],
            "cues": {},
        }

    cues = parse_srt(out_srt)
    pontos, total, falhas = avaliar_scorecard(cues)
    _, lint_str = rodar_linter(out_srt)
    print(f"  ✓ Concluído em {dt:.2f}s | Score: {pontos}/{total} | Linter: {lint_str}", flush=True)
    return {
        "name": name,
        "status": "OK",
        "time_s": round(dt, 2),
        "score": f"{pontos}/{total}",
        "lint": lint_str,
        "falhas": falhas,
        "cues": cues,
    }


def main():
    candidates = []

    if os.environ.get("GEMINI_TRANSLATE_KEY") or os.environ.get("GEMINI_TRANSLATE_KEYS") or os.environ.get("GEMINI_API_KEY"):
        candidates.append((
            "Gemini 3.0 Flash (auto)",
            [sys.executable, "traduz_gemini.py", "-m", "auto", "-b", "30", str(GOLDEN_SRT), str(OUT_DIR / "gemini_flash.pt-BR.srt")],
            OUT_DIR / "gemini_flash.pt-BR.srt",
            None,
        ))

    if os.environ.get("GROQ_API_KEY") or os.environ.get("GROK_API_KEY"):
        for groq_model, slug in [
            ("openai/gpt-oss-120b", "groq_120b"),
            ("qwen/qwen3.8-27b", "groq_qwen27b"),
            ("openai/gpt-oss-20b", "groq_20b"),
        ]:
            candidates.append((
                f"Groq ({groq_model})",
                [sys.executable, "traduz_groq.py", "-m", groq_model, "-b", "22", str(GOLDEN_SRT), str(OUT_DIR / f"{slug}.pt-BR.srt")],
                OUT_DIR / f"{slug}.pt-BR.srt",
                None,
            ))

    if os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN"):
        candidates.append((
            "HuggingFace (Llama-3.3-70B)",
            [sys.executable, "traduz_hf.py", "-b", "22", str(GOLDEN_SRT), str(OUT_DIR / "hf_llama70b.pt-BR.srt")],
            OUT_DIR / "hf_llama70b.pt-BR.srt",
            None,
        ))

    if os.environ.get("OPENROUTER_API_KEY"):
        candidates.append((
            "OpenRouter (Llama-3.3-70B)",
            [sys.executable, "traduz_openrouter.py", "-b", "22", str(GOLDEN_SRT), str(OUT_DIR / "openrouter_llama70b.pt-BR.srt")],
            OUT_DIR / "openrouter_llama70b.pt-BR.srt",
            None,
        ))

    if not candidates:
        print("Nenhuma chave de API configurada no ambiente.", file=sys.stderr)
        sys.exit(1)

    results = []
    for idx, (name, cmd, out_srt, env) in enumerate(candidates):
        if idx > 0 and "Groq" in name and "Groq" in candidates[idx - 1][0]:
            # Pequena pausa entre chamadas Groq para respeitar janela de 8k TPM
            time.sleep(15)
        results.append(run_candidate(name, cmd, out_srt, env))

    # Gera relatório Markdown
    lines = [
        "# Resultado do Benchmark — Golden Set Uzak Şehir (22 falas críticas)\n",
        "| Modelo / Motor | Status | Tempo | Scorecard (Armadilhas) | Linter 1:1 |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ]
    for r in results:
        lines.append(f"| **{r['name']}** | {r['status']} | {r['time_s']}s | **{r['score']}** | {r['lint']} |")

    lines.append("\n## Detalhes das Falhas por Modelo\n")
    for r in results:
        lines.append(f"### {r['name']} ({r['score']})")
        if not r["falhas"]:
            lines.append("- ✅ Passou em todas as 10 armadilhas!")
        else:
            for f in r["falhas"]:
                lines.append(f"- ⚠️ {f}")
        lines.append("")

    report_path = BENCH_DIR / "resultado_benchmark.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n==> Relatório salvo em: {report_path}")


if __name__ == "__main__":
    main()
