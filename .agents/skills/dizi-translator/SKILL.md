---
name: dizi-translator
description: >-
  Especialista em tradução de legendas de séries dramáticas turcas (dizis) para Português do Brasil (PT-BR),
  com foco em Uzak Şehir (Longe Demais), preservação rigorosa de gênero gramatical, coesão dramática,
  sincronismo milimétrico 1:1, recomendações de modelos de IA e geração automática de legendas .ass com tarja preta e texto amarelo.
---

# Dizi Translator — Especialista em Séries Turcas (Uzak Şehir)

Esta skill capacita o Antigravity a atuar como tradutor profissional de legendas de novelas e séries dramáticas turcas (*dizis*), garantindo máxima naturalidade no Português do Brasil (PT-BR) falado, preservação rigorosa de gênero, sincronismo milimétrico 1:1 e geração de legendas `.ass` prontas para reprodução no VLC/MPV.

---

## 1. Contexto e Universo de Uzak Şehir (Longe Demais - Mardin)

A série se passa em Mardin e gira em torno da rivalidade entre as famílias **Albora** e **Baybars**.

### Família Albora:
- **Azem Albora (In memoriam / Falecido):** O patriarca falecido fundador da autoridade familiar, marido de Dona Sadakat, pai de Boran, Cihan, Kaya e Nare. Irmão mais velho de Ecmel.
- **Cihan Albora (Masculino - Ozan Akbaba):** O chefe honrado da família Albora. Voz de autoridade, leal, firme e protetor. Primo de Şahin, filho de Azem e Dona Sadakat.
- **Sadakat Albora (Dona Sadakat) (Feminino - Gonca Cilasun):** Matriarca impiedosa, tradicional e manipuladora. Viúva de Azem, mãe de Cihan, Kaya, Boran e Nare. Deseja o controle absoluto do neto Deniz e inferniza a nora Alya.
  - **Atenção estrita de gênero:** O pronome turco *"o"* / *"onun"* referente a ela deve ser SEMPRE traduzido como *"ela"*, *"dela"*, *"a senhora"*, *"sua mãe"*. NUNCA traduza referências a Dona Sadakat como *"ele"* ou *"dele"*.
- **Alya Smith Albora (Dra. Alya) (Feminino - Sinem Ünsal):** Médica pediatra criada com valores ocidentais no Canadá, mãe protetora e inabalável de Deniz. Luta contra o cerco e as armadilhas de Dona Sadakat.
- **Boran Albora (Masculino):** Marido de Alya que foi dado como morto, mas depois reapareceu vivo em estado vegetativo/coma crítico (registrado temporariamente como Ömer Bakır). **Atenção:** Não tratar Boran como falecido após essa revelação na trama.
- **Kaya Albora (Masculino - Atakan Özkaya):** Filho caçula impulsivo e passional de Sadakat e Azem, irmão mais novo de Cihan, noivo de İpek.
- **İpek (Feminino):** Noiva de Kaya e futura NORA de Dona Sadakat.
- **Şahin Albora (Masculino - Alper Çankaya):** Primo de Cihan (filho de Ecmel e Fidan). Apaixonado por Nare, dividido entre o amor e a lealdade familiar. Não confundir com Cihan.
- **Nare Albora (Feminino - Sahra Şaş):** Irmã de Cihan, filha de Sadakat. Apaixonada por Şahin e grávida em segredo.
- **Deniz Cihan Albora (Masculino - Kuzey Gezer):** Menino de 5 anos, filho pequeno de Alya e Boran (fala com ingenuidade de criança de 5-6 anos).

### Outros Personagens e Núcleos Importantes:
- **Demir Baybars (Masculino - Ferit Kaya):** Arqui-inimigo da família Albora. Não deve ser marcado como orador em cenas domésticas da família Albora.
- **Ecmel Albora (Masculino - Müfit Kayacan):** Irmão mais novo e ambicioso do falecido Azem, tio de Cihan, pai de Şahin e Zerrin, marido de Fidan. Rival interno de Cihan pelo poder.
- **Fidan Albora (Feminino - İlkay Kayku Atalay):** Esposa de Ecmel, mãe de Şahin e Zerrin.
- **Zerrin Albora Baybars (Feminino - Dilin Döğer):** Filha de Ecmel e Fidan, irmã de Şahin, com ligação de casamento/conflito com a família rival Baybars. **Atenção de gênero:** referências a ela devem ser SEMPRE no feminino (*"ela"*, *"dela"*, *"minha filha"*, *"minha irmã"*).
- **Muzaffer Sancak (Masculino - Sinan Demirer):** Homem de confiança e funcionário de longa data da mansão Albora.
- **Pakize Sancak (Feminino - Yaren Güldiken):** Filha de Muzaffer, jovem empregada leal da mansão.
- **Hasan Karalı (Masculino - Mehmet Polat):** Figura envolvida nas disputas e alianças de poder locais.
- **Güler Haşmetlioğlu (Feminino):** Envolvida em processos e acusações criminais contra Dona Sadakat.
- **Mine (Feminino):** Envolvida cuja morte misteriosa desencadeia conflitos.
- **Dr. Yalçın (Masculino):** Médico amigo/colega de Alya.

---

## 2. Regras Essenciais de Tradução e Sincronismo

### A. Sincronismo Milimétrico 1:1 (Regra de Ouro)
- **Timestamps Inalterados:** Preserve os tempos originais (`00:xx:xx,xxx --> 00:xx:xx,xxx`) exatamente idênticos, sem adiantar nem atrasar um milissegundo sequer.
- **Proibido Fundir ou Dividir Blocos:** Cada fala original turca corresponde a exatamente uma fala traduzida (paridade 1:1) com o mesmo ID, garantindo que o diálogo entre e saia sincronizado perfeitamente com a boca do ator.
- **Concisão de Legenda:** Como diálogos em turco podem ser breves, mantenha a tradução em português direta e enxuta, evitando frases excessivamente longas que ultrapassem o tempo de tela.

### B. Preservação Rigorosa de Gênero Gramatical
- O turco usa pronomes de terceira pessoa neutros (*"o"*, *"onun"*, *"ona"*, *"ondan"*).
- **Regra de Ouro:** Identifique SEMPRE quem está falando e a quem a fala se refere antes de conjugar ou aplicar pronomes.
  - Quando Cihan, Ecmel, Kaya ou Şahin falam sobre **Sadakat** (mãe): *"ela"*, *"dela"*, *"a senhora"*, *"sua mãe"* (NUNCA *"ele"* ou *"dele"*).
  - Quando falam sobre **Zerrin** (filha sequestrada): *"ela"*, *"dela"*, *"minha filha"*, *"minha irmã"*.
  - Alya, İpek, Nare, Fidan: pronomes e adjetivos sempre femininos (*"obrigada"*, *"cansada"*, *"sozinha"*, *"preocupada"*).

### C. Alucinação de Orador (Speaker Attribution)
- Em discussões acaloradas ou diálogos rápidos, **NUNCA invente ou adivinhe o orador** se o contexto não for 100% explícito.
- **Cihan vs. Şahin:** Cihan é o patriarca firme; Şahin é o primo rebelde filho de Ecmel. Não troque a fala de Cihan por Şahin.
- **Demir Baybars:** Não atribua falas de discussões íntimas entre Ecmel e Fidan a Demir Baybars.
- **Em caso de dúvida:** Deixe a linha de diálogo limpa, sem o nome do orador, ou utilize tags descritivas neutras como `[Homem]:` ou `[Mulher]:`.

### D. Proibição de Vazamento de Turco (Zero Turkish Leakage)
- Nenhuma expressão turca comum pode passar sem tradução para PT-BR. Verifique rigorosamente:
  - *Tamam* ➔ *Tudo bem* / *Certo* / *Ok* / *Combinado*
  - *Ne oluyor?* ➔ *O que está acontecendo?* / *O que é isso?*
  - *Vay be* ➔ *Nossa!* / *Caramba!* / *Incrível!*
  - *Tipi sonra* ➔ Traduzir conforme o contexto de ação/clima.
  - *Hadi* ➔ *Vamos!* / *Anda logo!*

### E. Adaptação de Termos Culturais e Relações de Parentesco
- *"Sadakat Hanım"* ➔ *"Dona Sadakat"*
- **Apenas Dona Sadakat é a "Vovó" (Parentesco Exclusivo):** Dona Sadakat é a única avó de Deniz na trama. Senhoras idosas acolhedoras ou secundárias (ex: a mãe de Pakize na casa de campo da vila) NUNCA devem ser chamadas de *"vovó"* por Deniz, mesmo que o turco use expressões coloquiais como *"anneanne"*. Traduza sempre como *"a senhora"*, *"dona"* ou *"peça a bênção para a senhora"*. Isso preserva a lógica familiar e evita confusão com a matriarca Sadakat.
- *"Gelin"* / *"Gelinim"* ➔ Se dita pela sogra ou família do noivo (ex: Dona Sadakat para İpek), traduza OBRIGATORIAMENTE como *"Nora"* / *"Minha nora"* (NUNCA "minha noiva"). Se dita pelo próprio noivo (Kaya), traduza como *"Noiva"*.
- *"Damat"* / *"Damadım"* ➔ Se dita pelos sogros/família, traduza como *"Genro"* / *"Nosso genro"*. Se dita pela noiva, traduza como *"Noivo"*.
- *"Anne diyeceksin bana"* ➔ *"Vai me chamar de mãe"* (exigência tradicional da sogra para a nora na Turquia).
- *"Abla"* ➔ *"Irmã"* / *"Tia"*
- *"Abi"* ➔ *"Irmão"* / *"Meu irmão"*
- *"Yenge"* ➔ *"Cunhada"* (ou *"Dona Alya"*, dependendo do respeito do funcionário)
- *"Ağa"* / *"Ağam"* ➔ *"Patriarca"* / *"Chefe"* / *"Patrão"*
- *"Başım üstüne"* ➔ *"Às suas ordens"* / *"Com certeza"* / *"Conte com isso"*
- *"Allah aşkına"* ➔ *"Pelo amor de Deus"*
- *"Geçmiş olsun"* ➔ *"Melhoras"* / *"Que passe logo"*
- *"Konağa"* / *"Konak"* ➔ *"Mansão"*
- *"Helalim"* ➔ *"Legítima esposa"* / *"Minha mulher de direito"*

---

## 3. Recomendações de Modelos de IA e Limites de API (Rate Limits)

| Plataforma / Modelo | Perfil de Uso | Características & Destaques |
| :--- | :--- | :--- |
| **Google Gemini 3.0 Flash** (`gemini-3-flash-preview` / `gemini-flash-latest`) | **Melhor Custo-Benefício Gratuito** | Janela de contexto enorme, ideal para o script `traduz_gemini.py`. **Importante:** no Free Tier (15 RPM), deve usar pacing delay de **pelo menos 4.2 segundos** entre lotes para evitar erro HTTP 429 (`ResourceExhausted`). Nunca use versão 2.5 (inexistente). |
| **GPT-4o (ChatGPT Plus / OpenAI)** | **Melhor Qualidade Humana / Dramática** | Modelo padrão recomendado para tradução manual ou via Custom GPT. Fluência impecável em PT-BR, captação profunda de subtextos emocionais e fidelidade rigorosa a IDs. |
| **Llama 3.3 70B (via Groq Cloud)** | **Mais Rápido na Nuvem** | Velocidade de ~250–300 tokens/s no script `traduz_groq.py`. Nível de compreensão dramática muito superior a modelos de 8B. |
| **DeepSeek-V3 / Chat** | **Ultra Baixo Custo em Nuvem** | Custo irrisório (~R$ 0,30 por episódio de 2h) com 671B parâmetros e aderência estrita a formatos JSON. |
| **Qwen 2.5 7B Instruct Local (llama.cpp)** | **Melhor Opção Local / GitHub Actions** | Modelo `Qwen2.5-7B-Instruct-Q4_K_M.gguf`. Deve rodar com janela expandida de **8.192 tokens** (`--ctx-size 8192`), contexto anterior de **8 a 10 falas**, sem reasoning (`--reasoning off`), e `--threads 2` em runners de 2 vCPUs. Suporta execução em matriz dinâmica de até 16 runners simultâneos no Actions. |

---

## 4. Regra Obrigatória: Sempre Gerar Duas Versões de Legenda

Para cada episódio traduzido, devem ser geradas **SEMPRE duas versões completas** (tanto em `.srt` quanto em `.ass` estilizado):
1. **Versão com Identificação de Orador (`.com_orador.pt-BR.srt` e `.com_orador.ass`):**
   - Cada fala inicia com o nome de quem fala na cena (ex: `Cihan: ...`, `Alya: ...`, `Dona Sadakat: ...`, `Kaya: ...`, `[Policial]: ...`).
   - Essencial para acompanhar diálogos rápidos, conflitos acalorados ou falas em *off* (fora da tela).
2. **Versão Pura Cinematográfica (`.pt-BR.srt` e `.ass`):**
   - Legenda limpa tradicional sem os nomes dos oradores, focada na imersão direta e estética padrão de cinema/TV.

### Tratamento de Regex Unicode para Remoção de Oradores
Em turco, nomes próprios possuem caracteres especiais fora da faixa Latin-1 (`Ş`, `İ`, etc.). O script `gerar_versoes_legendas.py` utiliza a faixa Unicode `\u0100-\u017F`:
```python
SPEAKER_PATTERN = r'(?:\[[^\]]+\]|[A-ZÀ-ÖØ-Þ\u0100-\u017F][A-Za-zÀ-öø-ÿ\u0100-\u017F\.\'\-]+(?:\s+[A-Za-zÀ-öø-ÿ\u0100-\u017F\.\'\-]+){0,2})'
```
Isso impede que nomes como `Şahin:` ou `İpek:` escapem para a versão limpa.

---

## 5. Geração de Legenda Estilizada (.ass)

Para garantir visualização confortável e cobrir os hardsubs em inglês originais, converter o SRT para ASS usando:
- **Tarja preta delimitada por linha (Box / BorderStyle 3):** ajustada ao tamanho exato do texto, sem criar uma faixa preta vazia na tela.
- **Texto em amarelo vivo (`&H0000FFFF`), negrito, tamanho 36, margem vertical 68.**

```ini
[Script Info]
Title: Legenda PT-BR (Tarja Preta Delimitada + Amarelo)
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,36,&H0000FFFF,&H0000FFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,10,0,2,40,40,68,1
```

Script utilitário: `python3 /data/data/com.termux/files/home/media-pipeline/gerar_versoes_legendas.py <arquivo.com_orador.srt>`.

---

## 6. Diretórios Padrão
- **Pasta de destino local:** `/sdcard/Download/Longe Demais/` e `/sdcard/Download/Teste traducao/`
- **Diretório FTP da 2ª Temporada:** `/G/Series/Longe demais - Segunda Temporada/`

---

## 7. Automação e Disparo em Lote via GitHub Actions (CLI / MCP)

Para processar novos episódios ou lotes rapidamente na nuvem:

### A. Traduzir Legenda SRT Existente no FTP (Rápido, ~10-15 min)
Quando o arquivo `.srt` original em turco já está no FTP:
```bash
gh workflow run traduzir_legenda_ftp.yml \
  -f srt_filename="Uzak_Sehir_-_Episode_42.srt" \
  -f season="Segunda Temporada" \
  -f translator="gemini" \
  -f network_mode="vpn"
```

### B. Transcrever Vídeo MP4 + Traduzir Completo (~1h20 min)
Quando só existe o arquivo `.mp4` no FTP (fatia áudio, roda Whisper `large-v3-q5_0` em 4 runners paralelos e traduz via Gemini):
```bash
gh workflow run legendar_ftp.yml \
  -f video_filename="Uzak_Sehir_-_Episode_43.mp4" \
  -f season="Segunda Temporada" \
  -f whisper_model="large-v3-q5_0" \
  -f translator="gemini" \
  -f network_mode="vpn"
```

### C. Disparo em Lote Automatizado (Ex: Episódios 43 ao 50)
```bash
for ep in {43..50}; do
  echo "Disparando workflow para Episódio $ep..."
  gh workflow run legendar_ftp.yml \
    -f video_filename="Uzak_Sehir_-_Episode_${ep}.mp4" \
    -f season="Segunda Temporada" \
    -f whisper_model="large-v3-q5_0" \
    -f translator="gemini" \
    -f network_mode="vpn"
  sleep 3
done
```

### D. Sincronizar Legendas Ajustadas Localmente de Volta ao FTP
```bash
gh workflow run sincronizar_legendas_ftp.yml -f network_mode="vpn"
```

