---
name: dizi-translator
description: >-
  Traduz e revisa legendas de séries dramáticas turcas para Português do Brasil (PT-BR),
  com contexto de Uzak Şehir, cuidado com gênero, relações entre personagens e qualidade de leitura.
---

# Tradução de dizis turcas — Uzak Şehir

Use estas orientações ao traduzir ou revisar diálogos turcos de *Uzak Şehir* (Longe Demais). O objetivo é uma legenda natural, concisa e fiel à cena, sem inventar informação nem sacrificar sentido por regras mecânicas.

## Contexto da série

A história se passa em Mardin e acompanha principalmente as famílias Albora e Baybars. Use as informações abaixo como referência, sempre respeitando o episódio e o contexto fornecidos. **Não antecipe revelações de episódios posteriores.** Se não souber em que ponto da trama a cena ocorre, não introduza fatos de trama que não estejam no diálogo ou no material de contexto.

- **Cihan Albora:** homem, líder dos Albora; primo de Şahin; filho de Sadakat.
- **Sadakat Albora:** mulher, matriarca; mãe de Cihan, Kaya, Boran e Nare.
- **Alya Albora:** mulher, médica pediatra canadense e mãe de Deniz.
- **Boran Albora:** marido de Alya e pai de Deniz. Foi dado como morto e depois reapareceu vivo, em estado crítico, vegetativo e em coma. Após essa revelação, não o descreva como falecido. Aplique essa informação apenas a cenas posteriores à revelação.
- **Kaya Albora:** homem, irmão mais novo de Cihan; noivo de İpek.
- **İpek:** mulher, noiva de Kaya.
- **Şahin Albora:** homem, primo de Cihan; filho de Ecmel e Fidan; ligado amorosamente a Nare.
- **Nare:** mulher, irmã de Cihan e ligada amorosamente a Şahin.
- **Deniz:** menino, filho de Alya e Boran. Ajuste a voz infantil à idade aparente e ao momento da história; não fixe uma idade se ela não estiver confirmada no contexto.
- **Demir Baybars:** homem, rival dos Albora.
- **Ecmel:** homem, pai de Şahin e Zerrin, marido de Fidan e rival interno de Cihan.
- **Fidan:** mulher, mãe de Şahin e Zerrin, esposa de Ecmel.
- **Zerrin:** mulher, filha de Ecmel e Fidan, irmã de Şahin.
- **Güler Haşmetlioğlu, Mine, Dr. Yalçın e Pakize:** personagens secundários; preserve o gênero e as relações quando a cena/contexto os confirmar.

## Regras de tradução

### Sentido, contexto e gênero

- O turco **não marca gênero** nos pronomes de terceira pessoa *o, onun, ona, ondan*. Determine o referente pelo diálogo e pela continuidade da cena; não adivinhe quando não houver evidência suficiente. Em português, reformule a frase para evitar um pronome ambíguo quando isso soar natural.
- Preserve gênero, parentesco, intenção, registro, emoção e subtexto. Sadakat e Zerrin são mulheres; use formas femininas quando forem o referente confirmado. Não force gênero em falas cujo referente seja incerto.
- Mantenha continuidade entre falas quebradas em blocos usando o contexto, mas devolva cada ID solicitado separadamente. Não junte, divida, omita ou reordene blocos.
- Não corrija uma possível falha do Whisper como se fosse certeza. Use o áudio, a cena ou contexto confirmado para resolver nomes e palavras duvidosas; se não for possível, preserve uma tradução prudente em vez de inventar.
- Contexto de personagem é apoio para desambiguar, não autorização para acrescentar fatos que não aparecem na fala.

### Português brasileiro e concisão

- Escreva em PT-BR falado, natural e adequado ao tom dramático, sem literalidade artificial. Preserve tensão, afeto, ironia, tratamento formal e pausas relevantes.
- Seja conciso para facilitar a leitura, mas não corte informação, intenção ou nuance necessária para entender a cena.
- Traduza expressões turcas comuns conforme o contexto: *tamam* (certo, tudo bem, combinado), *ne oluyor?* (o que está acontecendo?), *vay be* (nossa, caramba), *hadi* (vamos, anda), *Allah aşkına* (pelo amor de Deus), *geçmiş olsun* (melhoras), *başım üstüne* (às suas ordens, pode deixar). Não aplique uma equivalência fixa quando a cena pedir outra.
- Adapte formas de tratamento sem apagar a relação entre personagens: *Hanım* pode ser “Dona” ou “Senhora”; *abi* e *abla* podem ser “irmão/irmã”, nome próprio ou outra forma natural; *yenge* pode ser “cunhada” ou um tratamento respeitoso. Escolha pela relação e pelo registro da cena.
- *Gelin/gelinim* pode significar “nora” ou “noiva”; use a relação e quem fala para decidir. *Damat/damadım* pode ser “genro” ou “noivo”. Não use “nora”/“genro” automaticamente sem confirmar a relação.
- *Ağa* pode ser título, forma de respeito ou referência a autoridade local; traduza pelo contexto, sem transliterar por padrão. *Konak* costuma referir-se à mansão/residência da família. *Helalim* exige adaptação contextual; evite soluções literais pouco naturais.
- Preserve nomes próprios e palavras estrangeiras intencionais. Não deixe escapar frases turcas comuns sem traduzir, mas não altere nomes, títulos ou trechos deliberadamente mantidos no original.

### Oradores

- Não atribua falas a personagens apenas com base no texto do SRT. Sem áudio, identificação fornecida ou contexto inequívoco, mantenha a fala sem etiqueta de orador.
- Só inclua nomes de oradores quando o formato solicitado exigir e houver identificação confiável. Não invente etiquetas genéricas como `[Homem]` ou `[Mulher]` para compensar falta de evidência.

## Integridade do SRT e sincronismo

- Na etapa de tradução, mantenha todos os IDs, a ordem, os timestamps e a separação dos blocos da entrada; retorne exatamente um texto por ID. Isso protege a correspondência com a transcrição, mas **não comprova sincronismo labial**.
- Os fluxos do projeto não têm todos o mesmo pós-processamento. `gerar_versoes_legendas.py` deriva uma versão com etiquetas já presentes e outra limpa, mantendo os tempos do SRT nessa etapa. `srt_para_ass.py`, por padrão, normaliza durações, pode remover marcadores isolados de música e renumera blocos ao regravar o SRT; o ASS representa tempos em centésimos de segundo. Portanto, não prometa preservação exata de timestamps no arquivo final sem verificar o fluxo executado.
- Confirme no workflow usado quais arquivos são produzidos: alguns jobs geram SRT/ASS com e sem orador; outros geram apenas o SRT traduzido e o ASS correspondente. A presença de um script no repositório não significa que todos os workflows o executem.
- Não altere regras de timing ou de geração de arquivos para resolver um problema de tradução. Se houver defeito no sincronismo, corrija e valide separadamente o fluxo que o causou.

## Modelos e execução

Os modelos disponíveis, nomes, limites, preços e parâmetros mudam. Consulte o workflow e o script ativos antes de recomendar ou configurar um modelo; não trate taxas, desempenho ou ranking fixo como garantidos. Para comparar qualidade, use o mesmo trecho representativo, avalie precisão de sentido, contexto entre lotes, naturalidade PT-BR, nomes/gênero e validade/completude dos IDs. A escolha do modelo não substitui revisão da legenda.

## Revisão de qualidade

Antes de concluir, confira:

1. Cada ID solicitado aparece uma vez, na ordem, sem linha vazia ou fala inventada.
2. Nomes, gênero, parentesco e tratamento são coerentes com a cena e com o ponto da trama.
3. Negações, perguntas, ameaças, pedidos, números e referências importantes foram preservados.
4. Possíveis erros de transcrição foram tratados com evidência, sem transformar hipóteses em fatos.
5. O texto soa natural em PT-BR e cabe confortavelmente na tela sem perda de conteúdo.
6. Não há turco residual em diálogo comum nem spoilers provenientes do contexto geral.

## Estilo ASS usado no projeto

Os utilitários atuais geram ASS com resolução 1280×720, Arial 36 em negrito, texto amarelo (`&H0000FFFF`), caixa preta delimitada (BorderStyle 3) e margem vertical 68. Confirme o script e o workflow antes de prometer esse estilo ou qualquer conjunto específico de arquivos, pois há mais de um caminho de geração.
