# Media Pipeline (Automação de Séries & Legendas)

Pipeline automatizado no GitHub Actions para:
1. **Baixar episódios** de sites como Turkish123 diretamente para o servidor FTP doméstico;
2. **Extrair áudio e transcrever** com `whisper.cpp` (Large-v3-Turbo + Silero VAD);
3. **Traduzir legendas** com contexto dramático para PT-BR (OpenRouter / Gemini / Groq);
4. **Gerar legendas `.ass` estilizadas** com tarja preta opaca (para cobrir hardsubs embutidos) e texto em amarelo vivo.

## Workflows Disponíveis

- **Baixar Episódios para FTP (Turkish123):** Baixa episódios individuais ou em lote e envia para `/G/Series/Longe demais - [Temporada]`.
- **Legendar Série via FTP:** Pega o vídeo do FTP, transcreve com Whisper, traduz para PT-BR e envia as legendas (`.pt-BR.srt` e `.ass`) de volta para o FTP.

## Secrets Necessários no Repositório

- `FTP_HOST`: Endereço do host FTP (ex: `ftp.meudominio.com`)
- `FTP_PORT`: Porta do FTP (ex: `21`)
- `FTP_USER`: Usuário do FTP
- `FTP_PASSWORD`: Senha do FTP
- `OPENROUTER_API_KEY`: Chave da API do OpenRouter
- `GEMINI_TRANSLATE_KEY`: (Opcional) Chave da API do Google AI Studio
- `GROQ_API_KEY`: (Opcional) Chave da API da Groq Cloud
