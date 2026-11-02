# Media Pipeline (Automação de Séries & Legendas)

Pipeline automatizado no GitHub Actions para:
1. **Baixar episódios** de sites como Turkish123 diretamente para o servidor FTP doméstico;
2. **Extrair áudio e transcrever** com `whisper.cpp` (Large-v3-Turbo + Silero VAD);
3. **Traduzir legendas** com contexto dramático para PT-BR (OpenRouter / Gemini / Groq);
4. **Gerar legendas `.ass` estilizadas** com tarja preta opaca (para cobrir hardsubs embutidos) e texto em amarelo vivo.

## Workflows Disponíveis

- **Baixar Episódios para FTP (Turkish123):** Baixa episódios individuais ou em lote e envia para `/G/Series/Longe demais - [Temporada]`.
- **Legendar Série via FTP:** Pega o vídeo do FTP, transcreve com Whisper, traduz para PT-BR e envia as legendas (`.pt-BR.srt` e `.ass`) de volta para o FTP.
- **Traduzir Legenda Existente do FTP:** Baixa um `.srt`, traduz com o mecanismo escolhido, gera `.ass` e envia ambos ao FTP.
- **Sincronizar Legendas Prontas com FTP:** Envia os arquivos versionados em `legendas_prontas/` para a pasta escolhida.

## Secrets Necessários no Repositório

- `FTP_HOST`: Endereço do host FTP (ex: `ftp.meudominio.com`)
- `FTP_PORT`: Porta do FTP (ex: `21`)
- `FTP_USER`: Usuário do FTP
- `FTP_PASSWORD`: Senha do FTP
- `OPENROUTER_API_KEY`: Chave da API do OpenRouter
- `GEMINI_TRANSLATE_KEY`: (Opcional) Chave da API do Google AI Studio
- `GROQ_API_KEY`: (Opcional) Chave da API da Groq Cloud

O workflow de legendagem também aceita `GROK_API_KEY` como alternativa a `GROQ_API_KEY`.

## Observações operacionais

- Os mecanismos de tradução falham explicitamente se a resposta omitir falas ou se um lote não puder ser traduzido após as tentativas. Confira o log do Action antes de considerar a legenda concluída.
- Os workflows usam FTP simples (`ftp://`), que não criptografa credenciais nem arquivos. Use uma conexão FTPS/SFTP no servidor e adapte os comandos de transferência antes de enviar dados por uma rede não confiável.
