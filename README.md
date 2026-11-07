# Media Pipeline (Automação de Séries & Legendas)

Pipeline automatizado no GitHub Actions para:
1. **Baixar episódios** de sites como Turkish123 diretamente para o servidor FTP doméstico;
2. **Extrair áudio e transcrever** com `whisper.cpp` (Large-v3-Turbo + Silero VAD);
3. **Traduzir legendas** com contexto dramático para PT-BR (OpenRouter / Gemini / Groq / Hugging Face / modelo local);
4. **Gerar legendas `.ass` estilizadas** com tarja preta opaca (para cobrir hardsubs embutidos) e texto em amarelo vivo.

## Workflows Disponíveis

- **Baixar Episódios para FTP (Turkish123):** Baixa episódios individuais ou em lote e envia para `/G/Series/Longe demais - [Temporada]`.
- **Legendar Série via FTP:** Pega o vídeo do FTP, transcreve com Whisper, traduz para PT-BR e envia as legendas (`.pt-BR.srt` e `.ass`) de volta para o FTP. O mecanismo `local` usa Qwen3-8B GGUF Q4 via llama.cpp no runner Ubuntu.
- **Traduzir Legenda Existente do FTP:** Baixa um `.srt`, traduz com o mecanismo escolhido (Gemini, Groq, OpenRouter ou local), gera `.ass` e envia ambos ao FTP.
- **Sincronizar Legendas Prontas com FTP:** Envia os arquivos versionados em `legendas_prontas/` para a pasta escolhida.

## Secrets Necessários no Repositório

- `FTP_HOST`: Endereço do host FTP (ex: `ftp.meudominio.com`)
- `FTP_PORT`: Porta do FTP (ex: `21`)
- `FTP_USER`: Usuário do FTP
- `FTP_PASSWORD`: Senha do FTP
- `OPENROUTER_API_KEY`: Chave da API do OpenRouter
- `GEMINI_TRANSLATE_KEY`: (Opcional) Chave da API do Google AI Studio
- `GROQ_API_KEY`: (Opcional) Chave da API da Groq Cloud
- `HF_TOKEN`: (Opcional) Token do Hugging Face para o mecanismo `huggingface` (`HUGGINGFACE_HUB_TOKEN` também é aceito)

O workflow de legendagem também aceita `GROK_API_KEY` como alternativa a `GROQ_API_KEY`.

O CLI local aceita `--engine gemini`, `groq`, `openrouter`, `huggingface`, `local` ou `skip`. Hugging Face usa `HF_TOKEN` (ou `HUGGINGFACE_HUB_TOKEN`); o modo `local` exige um `llama-server` já iniciado, compatível com a API OpenAI, em `LOCAL_LLM_URL` (padrão `http://127.0.0.1:8080/v1/chat/completions`).

## Observações operacionais

- Os mecanismos de tradução falham explicitamente se a resposta omitir falas ou se um lote não puder ser traduzido após as tentativas. Confira o log do Action antes de considerar a legenda concluída.
- O mecanismo local baixa um modelo GGUF de aproximadamente 5 GB na primeira execução; o GitHub Actions tenta reutilizar o modelo e o binário llama.cpp pelo cache.
- No workflow de teste, Aya 23 usa a API nativa `/completion` do llama.cpp com os tokens de conversa Cohere e JSON Schema. Isso evita o parser de saída de chat `peg-native`. Os IDs são validados explicitamente; falhas definitivas interrompem o shard sem substituir traduções pelo texto original. Checkpoints anteriores a essa correção são descartados para não reutilizar resultados inválidos.
- Os workflows usam FTP simples (`ftp://`), que não criptografa credenciais nem arquivos. Use uma conexão FTPS/SFTP no servidor e adapte os comandos de transferência antes de enviar dados por uma rede não confiável.
