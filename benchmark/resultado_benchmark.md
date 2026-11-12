# Resultado do Benchmark — Golden Set Uzak Şehir (22 falas críticas)

| Modelo / Motor | Status | Tempo | Scorecard (Armadilhas) | Linter 1:1 |
| :--- | :---: | :---: | :---: | :---: |
| **Groq (openai/gpt-oss-120b)** | OK | 2.73s | **5/10** | PASS (avisos=?) |
| **Groq (qwen/qwen3.8-27b)** | OK | 174.22s | **9/10** | PASS (avisos=?) |
| **Groq (openai/gpt-oss-20b)** | OK | 59.02s | **4/10** | PASS (avisos=?) |

## Detalhes das Falhas por Modelo

### Groq (openai/gpt-oss-120b) (5/10)
- ⚠️ #5 Çıkmasın traduzido sem 3ª pessoa (Deniz): 'Não saia.'
- ⚠️ #6/#12 Kurban literal ('sacrifício'): #6='Eu me sacrificaria se você não conseguir sair.' | #12='Durma, meu sacrifício.'
- ⚠️ #8 Parlama literal ('brilhar'): 'Dona Alya, pare de brilhar novamente.'
- ⚠️ #13 Ayağına sağlık literal ('saúde nos pés'): 'Vai, que Deus lhe dê saúde nos pés, irmão, e a você também.'
- ⚠️ #17/#19/#20 Cena Sadakat/Alya: #17='Vou entregar o culpado.' | #19='Não nos aceite mais como convidados.' | #20='Sua generosidade já é suficiente.'

### Groq (qwen/qwen3.8-27b) (9/10)
- ⚠️ #17/#19/#20 Cena Sadakat/Alya: #17='Devo entregar seu documento.' | #19='Não me tratem mais como uma nora.' | #20='Esse título de 'caridade' já é suficiente.'

### Groq (openai/gpt-oss-20b) (4/10)
- ⚠️ #2 Boran virou Bora/outro: 'Transferiremos o rim que recebermos de Cihan para Bora simultaneamente.'
- ⚠️ #5 Çıkmasın traduzido sem 3ª pessoa (Deniz): 'Não saia.'
- ⚠️ #6/#12 Kurban literal ('sacrifício'): #6='Eu me sacrificaria, mas se não puder sair?' | #12='Durma, meu sacrifício.'
- ⚠️ #8 Parlama literal ('brilhar'): 'Alya, pare de brilhar de novo.'
- ⚠️ #9 Ecmui/Allah razı olsun literal: 'Que Deus o agradeça, pai Ecmui.'
- ⚠️ #17/#19/#20 Cena Sadakat/Alya: #17='Deixe-me entregar o juiz.' | #19='Não me considerem mais como 'venham aqui'.' | #20='Sadakat, eu te conheço muito bem.'
