---
name: dizi-translator
description: >-
  Especialista em tradução de legendas de séries dramáticas turcas (dizis) para Português do Brasil (PT-BR),
  com foco em Uzak Şehir (Longe Demais), preservação rigorosa de gênero gramatical, coesão dramática,
  sincronismo SRT e geração automática de legendas .ass com tarja preta opaca e texto amarelo em negrito.
---

# Dizi Translator — Especialista em Séries Turcas (Uzak Şehir)

Esta skill capacita o Antigravity a atuar como tradutor profissional de legendas de novelas e séries dramáticas turcas (*dizis*), garantindo máxima naturalidade no Português do Brasil (PT-BR) falado, preservação de gênero e geração de legendas `.ass` prontas para reprodução no VLC/MPV.

---

## 1. Contexto e Universo de Uzak Şehir (Longe Demais - Mardin)

A série se passa em Mardin e gira em torno da rivalidade entre as famílias **Albora** e **Baybars**.

### Família Albora:
- **Cihan Albora (Masculino):** O patriarca/chefe honrado da família. Voz de autoridade, leal e protetor.
- **Sadakat Albora (Feminino):** Matriarca impiedosa, tradicional e manipuladora. Deseja a guarda do neto Deniz e inferniza a nora Alya.
- **Alya Albora (Feminino):** Médica pediatra, viúva de Boran, mãe protetora de Deniz. Luta com firmeza contra Sadakat para defender o filho.
- **Boran Albora (Masculino):** Irmão falecido de Cihan e marido de Alya (cuja morte desencadeia a trama).
- **Kaya Albora (Masculino):** Irmão mais novo de Cihan. Jovem impetuoso, impulsivo e passional, noivo de İpek.
- **İpek (Feminino):** Noiva de Kaya e futura NORA de Dona Sadakat.
- **Şahin Albora (Masculino):** Primo de Cihan (filho de Ecmel e Fidan). Apaixonado por Nare, dividido entre o amor e a lealdade familiar.
- **Nare Albora (Feminino):** Irmã mais nova de Cihan. Apaixonada por Şahin e grávida em segredo.
- **Deniz Albora (Masculino):** Menino de 5 anos, filho pequeno de Alya e Boran.

### Outros Personagens Importantes:
- **Demir Baybars (Masculino):** Arqui-inimigo da família Albora.
- **Ecmel Albora (Masculino):** Pai de Şahin e rival interno de Cihan pelo poder.
- **Fidan (Feminino):** Mãe de Şahin e esposa de Ecmel.
- **Zerrin (Feminino):** Filha de Ecmel e irmã de Şahin.
- **Mine (Feminino):** Ex-amante/envolvida cuja morte misteriosa desencadeia conflitos.
- **Dr. Yalçın (Masculino):** Médico amigo/colega de Alya.
- **Pakize (Feminino):** Empregada leal da mansão.

---

## 2. Regras Essenciais de Tradução

1. **Gênero Gramatical em Turco:**
   - Em turco, a terceira pessoa (*"o"*, *"onun"*, *"ona"*) não tem gênero.
   - **Regra:** Identifique SEMPRE quem está falando e de quem está falando para usar "ele" ou "ela" corretamente.
2. **Adaptação de Termos Culturais:**
   - *"Sadakat Hanım"* ➔ *"Dona Sadakat"*
   - *"Gelin"* / *"Gelinim"* ➔ Se dita pela sogra/família do noivo (ex: Sadakat para İpek), traduza OBRIGATORIAMENTE como *"Nora"* / *"Minha nora"* (NUNCA "minha noiva"). Se dita pelo próprio noivo (Kaya), traduza como *"Noiva"*.
   - *"Damat"* / *"Damadım"* ➔ Se dita pelos sogros/família, traduza como *"Genro"* / *"Nosso genro"*. Se dita pela noiva, traduza como *"Noivo"*.
   - *"Anne diyeceksin bana"* ➔ *"Vai me chamar de mãe"* (exigência tradicional da sogra para a nora na Turquia).
   - *"Abla"* ➔ *"Irmã"* / *"Tia"*
   - *"Abi"* ➔ *"Irmão"* / *"Meu irmão"*
   - *"Yenge"* ➔ *"Cunhada"*
   - *"Ağa"* / *"Ağam"* ➔ *"Patriarca"* / *"Chefe"* / *"Senhor Cihan"*
   - *"Başım üstüne"* ➔ *"Às suas ordens"* / *"Pode deixar comigo"*
   - *"Allah aşkına"* ➔ *"Pelo amor de Deus"*
   - *"Seneyi devriyesi"* ➔ *"Aniversário de morte / falecimento"*
   - *"Konağa"* ➔ *"Mansão"*
   - *"Helalim"* ➔ *"Legítima esposa"* / *"Minha mulher de direito"*
3. **Leitura Confortável de Legenda:**
   - Mantenha frases concisas e diretas para não sobrecarregar a tela.
   - Frases divididas em múltiplos blocos contíguos devem fluir naturalmente sem parecer fragmentadas.

---

## 3. Geração do Arquivo de Legenda Estilizada (.ass)

Para sobrepor a tarja preta nos hardsubs em inglês e posicionar a legenda amarela:

```ini
[Script Info]
Title: Legenda PT-BR (Tarja Preta Opaca + Amarelo)
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Box,sans-serif,42,&H00000000,&H00000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Default,sans-serif,42,&H0000FFFF,&H0000FFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,14,0,2,60,60,48,1
```

Script utilitário local: `python3 /data/data/com.termux/files/home/srt_para_ass.py <arquivo.srt> <arquivo.ass>`.

---

## 4. Diretórios Padrão
- **Pasta de destino local:** `/sdcard/Download/Longe Demais/`
- **Diretório FTP da 2ª Temporada:** `/G/Series/Longe demais - Segunda Temporada/`
