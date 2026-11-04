#!/usr/bin/env python3
"""
Orquestrador Central do Media Pipeline (CLI Modular)
Permite executar todas as etapas localmente ou em runners com um único comando:
- lint: validação de qualidade e contagem 1:1 de legendas
- render: geração de todas as 4 variantes (.srt limpo, .com_orador.srt, .ass, .com_orador.ass)
- notify: envio de notificação via WhatsApp (Evolution API)
- pipeline: fluxo completo local (traduzir -> normalizar -> renderizar -> validar -> notificar)
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def run_command(cmd, desc=""):
    if desc:
        print(f"\n===> {desc}...", flush=True)
    res = subprocess.run(cmd, cwd=str(BASE_DIR))
    if res.returncode != 0:
        print(f"❌ Falha ao executar: {' '.join(str(c) for c in cmd)} (código {res.returncode})", file=sys.stderr)
        return False
    return True


def cmd_lint(args):
    pt_path = Path(args.ptbr_srt).expanduser()
    cmd = [sys.executable, str(BASE_DIR / "lint_legendas.py"), str(pt_path)]
    if args.original:
        cmd.extend(["-o", str(Path(args.original).expanduser())])
    if args.ass:
        cmd.extend(["-a", str(Path(args.ass).expanduser())])
    if args.strict:
        cmd.append("--strict")
    return run_command(cmd, f"Validando qualidade de {pt_path.name}")


def cmd_render(args):
    srt_path = Path(args.srt).expanduser()
    cmd = [sys.executable, str(BASE_DIR / "gerar_versoes_legendas.py"), str(srt_path)]
    if args.out_dir:
        cmd.extend(["--out-dir", str(Path(args.out_dir).expanduser())])
    return run_command(cmd, f"Gerando 4 variantes de legendas para {srt_path.name}")


def cmd_notify(args):
    cmd = [sys.executable, str(BASE_DIR / "notificar_whatsapp.py"), args.message, "--status", args.status]
    if args.to:
        cmd.extend(["--to", args.to])
    return run_command(cmd, "Enviando notificação WhatsApp")


def cmd_run(args):
    input_file = Path(args.input_srt).expanduser()
    if not input_file.is_file():
        print(f"Erro: Arquivo de entrada não encontrado: {input_file}", file=sys.stderr)
        return False

    out_dir = Path(args.out_dir).expanduser() if args.out_dir else BASE_DIR / "legendas_prontas"
    out_dir.mkdir(parents=True, exist_ok=True)
    base_name = input_file.name.replace(".pt-BR.srt", "").replace(".srt", "")

    # 1. Tradução se solicitada
    translated_srt = input_file
    if args.engine != "skip":
        translated_srt = out_dir / f"{base_name}.pt-BR.srt"
        if args.engine == "gemini":
            cmd = [sys.executable, str(BASE_DIR / "traduz_gemini.py"), str(input_file), str(translated_srt)]
            if not run_command(cmd, f"Traduzindo com Gemini: {input_file.name}"):
                return False
        elif args.engine == "groq":
            cmd = [sys.executable, str(BASE_DIR / "traduz_groq.py"), str(input_file), str(translated_srt)]
            if not run_command(cmd, f"Traduzindo com Groq: {input_file.name}"):
                return False
        elif args.engine == "openrouter":
            cmd = [sys.executable, str(BASE_DIR / "traduz_openrouter.py"), str(input_file), str(translated_srt)]
            if not run_command(cmd, f"Traduzindo com OpenRouter: {input_file.name}"):
                return False

    # 2. Renderização das 4 variantes
    render_cmd = [sys.executable, str(BASE_DIR / "gerar_versoes_legendas.py"), str(translated_srt), "--out-dir", str(out_dir)]
    if not run_command(render_cmd, f"Gerando 4 variantes em {out_dir}"):
        return False

    # 3. Linter / Quality Gate
    ass_path = out_dir / f"{base_name}.ass"
    lint_cmd = [sys.executable, str(BASE_DIR / "lint_legendas.py"), str(translated_srt), "-o", str(input_file)]
    if ass_path.is_file():
        lint_cmd.extend(["-a", str(ass_path)])
    if not run_command(lint_cmd, "Executando Quality Gate (Linter 1:1)"):
        print("⚠️ Aviso: O linter encontrou divergências.", file=sys.stderr)

    # 4. Notificação WhatsApp se configurada
    if args.notify:
        msg = f"🎉 *{base_name}* processado com sucesso!\n📁 Arquivos gerados nas 4 variantes em `{out_dir.name}/`."
        cmd_not = [sys.executable, str(BASE_DIR / "notificar_whatsapp.py"), msg, "--status", "success"]
        if args.notify_to:
            cmd_not.extend(["--to", args.notify_to])
        run_command(cmd_not, "Notificando conclusão via WhatsApp")

    print(f"\n✅ Pipeline concluído com sucesso para {base_name}!\n", flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description="Media Pipeline CLI - Orquestrador Central")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcomando run
    p_run = subparsers.add_parser("run", help="Executa o pipeline completo (traduzir, renderizar, validar, notificar)")
    p_run.add_argument("input_srt", help="Arquivo .srt de entrada")
    p_run.add_argument("--engine", choices=["gemini", "groq", "openrouter", "skip"], default="skip", help="Motor de tradução (default: skip se já for pt-br)")
    p_run.add_argument("--out-dir", help="Diretório de saída (default: legendas_prontas)")
    p_run.add_argument("--notify", action="store_true", help="Enviar notificação no WhatsApp ao finalizar")
    p_run.add_argument("--notify-to", help="Número do WhatsApp para notificação")
    p_run.set_defaults(func=cmd_run)

    # Subcomando lint
    p_lint = subparsers.add_parser("lint", help="Valida conformidade 1:1 e qualidade de legendas")
    p_lint.add_argument("ptbr_srt", help="Arquivo .pt-BR.srt a ser validado")
    p_lint.add_argument("-o", "--original", help="Arquivo original em turco para comparar")
    p_lint.add_argument("-a", "--ass", help="Arquivo .ass estilizado correspondente")
    p_lint.add_argument("--strict", action="store_true", help="Falhar com erro em qualquer aviso")
    p_lint.set_defaults(func=cmd_lint)

    # Subcomando render
    p_render = subparsers.add_parser("render", help="Gera as 4 versões padrão (.srt limpo, .com_orador.srt, .ass, .com_orador.ass)")
    p_render.add_argument("srt", help="Arquivo .srt traduzido")
    p_render.add_argument("--out-dir", help="Diretório de saída")
    p_render.set_defaults(func=cmd_render)

    # Subcomando notify
    p_notify = subparsers.add_parser("notify", help="Envia mensagem via WhatsApp Evolution API")
    p_notify.add_argument("message", help="Mensagem de texto")
    p_notify.add_argument("--status", choices=["success", "warning", "error", "info"], default="info", help="Status")
    p_notify.add_argument("--to", help="Destinatário")
    p_notify.set_defaults(func=cmd_notify)

    args = parser.parse_args()
    success = args.func(args)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
