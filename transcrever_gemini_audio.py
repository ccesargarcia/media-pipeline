#!/usr/bin/env python3
"""
Transcreve e traduz áudio diretamente usando a API Multimodal do Google Gemini.
Escuta o áudio original em turco e gera o arquivo SRT sincronizado em Português do Brasil (PT-BR),
com identificação nativa do orador (ex: 'Cihan: ...', 'Alya: ...').
"""
import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://generativelanguage.googleapis.com"
UPLOAD_BASE = "https://generativelanguage.googleapis.com/upload/v1beta/files"

# Modelos em conformidade com as regras de disponibilidade Gemini (versão 3.x)
PREFERRED_MODELS = [
    "gemini-3.0-flash",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
]

PROMPT_UZAK_SEHIR = """Você é um especialista profissional em transcrição auditiva e legendagem da série dramática turca 'Uzak Şehir' (Longe Demais), ambientada em Mardin.

SUA MISSÃO:
Escute com extrema atenção a faixa de áudio em turco deste trecho e gere a legenda COMPLETA no formato padrão SRT traduzida diretamente para o Português do Brasil (PT-BR), com sincronismo milimétrico (00:00:00,000 --> 00:00:00,000).

CONTEXTO DRAMÁTICO E PERSONAGENS:
- Cihan Albora: Patriarca honrado e firme da família Albora. Voz autoritária, calma e protetora.
- Sadakat Albora (Dona Sadakat): Matriarca implacável e tradicional. Deseja o controle da família e inferniza Alya.
- Dra. Alya: Médica elegante e corajosa, mãe de Deniz.
- Deniz: Menino de 5 anos, filho de Alya. ATENÇÃO: Apenas Alya o chama de 'Deniz'. Dona Sadakat e os parentes tradicionais o chamam de 'Cihan' ou 'Cihancık' (em homenagem ao avô). Não confunda as falas do menino com o tio Cihan!
- Boran Albora: Marido de Alya que estava em coma.
- Kaya Albora: Irmão mais novo e impulsivo de Cihan, noivo de İpek.
- İpek: Noiva de Kaya e futura NORA de Dona Sadakat.
- Şahin Albora: Primo impulsivo (filho de Ecmel e Fidan), apaixonado por Nare.
- Nare Albora: Irmã de Cihan, grávida em segredo de Şahin. Tratamentos entre Nare e Şahin são amorosos ('meu amor', 'meu bem', NUNCA 'filho').
- Demir Baybars: Inimigo mortal dos Albora.

REGRAS OBRIGATÓRIAS:
1. IDENTIFICAÇÃO DO ORADOR: Inicie cada fala indicando quem está falando na cena seguido de dois pontos.
   Exemplos:
   Cihan: Me passe o relatório.
   Dona Sadakat: Não quero ouvir mais nada.
   Alya: Deniz, venha aqui agora.
   [Policial]: Documentos do veículo, por favor.
2. SINCRONISMO: Cada fala deve começar exatamente no momento em que o personagem abre a boca e terminar quando ele para de falar.
3. TRILHA SONORA E MÚSICA: As novelas turcas possuem trilhas sonoras instrumentais dramáticas altas. NÃO descarte falas que ocorram sob a música. Transcreva com fidelidade mesmo quando houver música de fundo ou choro.
4. GÊNERO GRAMATICAL: O turco usa pronomes neutros. Identifique pelo som da voz e contexto quem fala (ele/ela, obrigado/obrigada).
5. SAÍDA PURA: Retorne APENAS o bloco de legendas SRT válido, sem explicações antes ou depois.

Comece agora:"""


def get_api_key() -> str:
    key = os.environ.get("GEMINI_TRANSLATE_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        print("Erro: Nenhuma chave de API encontrada em GEMINI_TRANSLATE_KEY ou GEMINI_API_KEY.", file=sys.stderr)
        sys.exit(1)
    return key.strip()


def convert_to_lightweight_audio(input_path: Path, output_dir: Path) -> Path:
    """Converte o áudio para MP3 mono de 48kbps para acelerar o upload."""
    mp3_path = output_dir / f"{input_path.stem}_gemini.mp3"
    if mp3_path.is_file() and mp3_path.stat().st_size > 0:
        return mp3_path

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(input_path),
        "-vn", "-af", "highpass=f=150,lowpass=f=4000,volume=1.3",
        "-acodec", "libmp3lame", "-b:a", "48k", "-ar", "16000", "-ac", "1",
        str(mp3_path)
    ]
    subprocess.run(cmd, check=True)
    return mp3_path


def upload_audio_to_gemini(file_path: Path, api_key: str) -> dict:
    """Faz upload do áudio usando a Google AI Studio Files API (resumable protocol)."""
    file_size = file_path.stat().st_size
    mime_type = "audio/mp3"

    print(f"Iniciando upload de {file_path.name} ({file_size / (1024*1024):.2f} MB) para a Google File API...", flush=True)

    init_url = f"{UPLOAD_BASE}?key={api_key}"
    init_headers = {
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(file_size),
        "X-Goog-Upload-Header-Content-Type": mime_type,
        "Content-Type": "application/json",
    }
    init_body = json.dumps({"file": {"display_name": file_path.name}}).encode("utf-8")

    req = urllib.request.Request(init_url, data=init_body, headers=init_headers, method="POST")
    with urllib.request.urlopen(req) as resp:
        upload_url = resp.headers.get("x-goog-upload-url")
        if not upload_url:
            raise RuntimeError("Não foi possível obter o 'x-goog-upload-url' da API do Google.")

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    upload_headers = {
        "Content-Length": str(file_size),
        "X-Goog-Upload-Offset": "0",
        "X-Goog-Upload-Command": "upload, finalize",
    }
    req_upload = urllib.request.Request(upload_url, data=file_bytes, headers=upload_headers, method="POST")
    with urllib.request.urlopen(req_upload) as resp:
        res_data = json.loads(resp.read().decode("utf-8"))
        file_info = res_data.get("file", {})
        print(f"Upload concluído! URI: {file_info.get('uri')} | Nome: {file_info.get('name')}", flush=True)
        return file_info


def delete_gemini_file(file_name: str, api_key: str):
    """Remove o arquivo temporário da conta Google."""
    try:
        del_url = f"{API_BASE}/v1beta/{file_name}?key={api_key}"
        req = urllib.request.Request(del_url, method="DELETE")
        with urllib.request.urlopen(req) as resp:
            pass
    except Exception as e:
        print(f"Aviso ao deletar arquivo temporário {file_name}: {e}", file=sys.stderr)


def transcrever_com_gemini(file_uri: str, api_key: str, model_name: str) -> str:
    """Chama o generateContent do Gemini com o áudio e o prompt especializado."""
    endpoint = f"{API_BASE}/v1beta/models/{model_name}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "file_data": {
                            "mime_type": "audio/mp3",
                            "file_uri": file_uri,
                        }
                    },
                    {
                        "text": PROMPT_UZAK_SEHIR
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 8192,
        }
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(endpoint, data=req_data, headers={"Content-Type": "application/json"}, method="POST")

    with urllib.request.urlopen(req, timeout=300) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        candidates = res.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"Nenhum candidato retornado pelo Gemini: {res}")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        return text


def clean_srt_response(raw_text: str) -> str:
    """Extrai blocos SRT removendo possíveis cercas de código markdown."""
    text = re.sub(r"^```(?:srt)?", "", raw_text.strip(), flags=re.MULTILINE)
    text = re.sub(r"```$", "", text.strip(), flags=re.MULTILINE)
    return text.strip()


def main():
    parser = argparse.ArgumentParser(description="Transcreve e traduz áudio diretamente com Gemini")
    parser.add_argument("audio_path", help="Caminho do arquivo de áudio (wav, mp3, etc.)")
    parser.add_argument("saida_srt", help="Caminho de saída para o arquivo .srt")
    args = parser.parse_args()

    audio_file = Path(args.audio_path).resolve()
    saida_srt = Path(args.saida_srt).resolve()
    if not audio_file.is_file():
        print(f"Erro: Arquivo de áudio não encontrado: {audio_file}", file=sys.stderr)
        sys.exit(1)

    api_key = get_api_key()
    work_dir = saida_srt.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    mp3_file = convert_to_lightweight_audio(audio_file, work_dir)
    file_info = upload_audio_to_gemini(mp3_file, api_key)
    file_name = file_info.get("name")
    file_uri = file_info.get("uri")

    try:
        srt_text = None
        for model in PREFERRED_MODELS:
            print(f"Tentando transcrever e traduzir com o modelo {model}...", flush=True)
            try:
                srt_text = transcrever_com_gemini(file_uri, api_key, model)
                print(f"Sucesso com o modelo {model}!", flush=True)
                break
            except urllib.error.HTTPError as he:
                print(f"Erro HTTP {he.code} ao chamar {model}: {he.read().decode('utf-8', errors='replace')[:300]}", file=sys.stderr)
                time.sleep(2)
            except Exception as e:
                print(f"Erro ao tentar modelo {model}: {e}", file=sys.stderr)
                time.sleep(2)

        if not srt_text:
            raise RuntimeError("Nenhum modelo Gemini conseguiu processar o áudio com sucesso.")

        cleaned_srt = clean_srt_response(srt_text)
        saida_srt.write_text(cleaned_srt + "\n", encoding="utf-8")
        print(f"Arquivo SRT salvo com sucesso em: {saida_srt}", flush=True)

    finally:
        if file_name:
            print(f"Removendo arquivo temporário {file_name} da Google API...", flush=True)
            delete_gemini_file(file_name, api_key)
        if mp3_file.is_file() and mp3_file != audio_file:
            mp3_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
