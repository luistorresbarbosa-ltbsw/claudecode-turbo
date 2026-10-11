# Piloto: Claude Code standard vs JEV + modelos free

Data: 2026-10-11 · Estado: para revisão

## 1. Objetivo

Correr o mesmo projeto pequeno em dois braços, com o **mesmo envelope de tempo e de custo** definido
pelo utilizador, e comparar o que cada um consegue:

- **standard**: Claude Code com o modelo e o esforço por defeito do utilizador (opus · xhigh) em todas as tarefas;
- **jev**: cada tarefa passa pelo Jev (`typesafe/jev-router`), que decide: Anthropic pela subscrição,
  com o modelo e o esforço dele, ou, nas tarefas simples, um modelo free. Fallback para o standard.

No fim, uma avaliação em duas camadas: **medições objetivas** feitas pelo harness, e um **juiz LLM**
(Opus 5.5, às cegas e com a ordem trocada) para o que os testes não veem. O dashboard mostra tudo.

### Critérios de sucesso (do harness, não do JEV)

1. Um comando corre o piloto inteiro sem intervenção e respeita os envelopes.
2. Cada tarefa, em cada braço, fica registada com custo, tempo real, modelo e resultado da aceitação.
3. O scorecard mostra conclusão, custo, tempo, custo por tarefa concluída, performance, higiene e
   veredictos do juiz.
4. O avaliador é validado antes da primeira chamada paga: a solução de referência conclui 8/8 tarefas,
   o projeto inicial 0/8, e o juiz chumba lixo. A aceitação conta-se **por tarefa, tudo ou nada**.

### Fora do âmbito

- Repetições (n > 1) e estatística. Fica para depois, se o envelope der folga.
- Correr os braços em paralelo, que contaminaria os tempos.
- Projetos noutras linguagens.

## 2. O projeto `fatura`

Uma mini-biblioteca Python de faturas portuguesas. É simples de explicar e traiçoeira nos detalhes.

### 2.1 Ponto de partida (igual nos dois braços)

```
fatura/
  pyproject.toml          python 3.12, pytest como dependência de desenvolvimento
  README.md               convenções: Decimal em todo o lado, ROUND_HALF_UP a 2 casas
  fatura/__init__.py
  fatura/modelo.py        Linha(descricao, quantidade, preco_unitario, taxa, desconto_pct)
                          Fatura(numero, regiao, linhas); taxa ∈ {NOR, INT, RED}; regiao ∈ {PT, PT-MA, PT-AC}
  fatura/iva.py           TAXAS[regiao][taxa] -> Decimal  (bug semeado: PT-MA NOR = 0.32)
  tests/test_iva.py       testes visíveis; o da Madeira falha por causa do bug
```

### 2.2 Tarefas

Os prompts são iguais nos dois braços e correm por esta ordem. **As tarefas de texto não mencionam
ficheiros**: se mencionassem, o Jev classificava-as como `code:file_read_write` e iam para o haiku em
vez de um free. Um free não escreve ficheiros, por isso em ambos os braços é o harness que grava a
resposta em `docs/`. As tarefas são **independentes entre si**: cada uma
só depende do ponto de partida e dos seus próprios ficheiros injetados, para que uma falha não arraste
as seguintes.

| # | Título | Tipo | Espero | Ficheiro de saída / injetado |
|---|---|---|---|---|
| T1 | Glossário de IVA | texto | free | → `docs/IVA.md` |
| T2 | Bug da Madeira | código | haiku (barato + ficheiros) | — |
| T3 | Validar NIF | código | haiku | — |
| T4 | Totais da fatura | código | sonnet | — |
| T5 | JSON + CLI | código | haiku ou sonnet | — |
| T6 | O cêntimo que falta | código | opus | injeta `fatura/notas_credito.py` + `exemplos/ft-2026-31.json` |
| T7 | Reconciliação bancária | código | **opus** (Fable só se o Jev o admitir) | — |
| T8 | Email ao cliente | texto | free | → `docs/email-aurora.md` |

A coluna "Espero" é só a minha previsão, para o relatório. **Quem decide é o JEV.**

Prompts:

- **T1.** "Escreve um glossário curto, em português de Portugal, das taxas de IVA em vigor em Portugal:
  continente, Madeira e Açores, com as taxas normal, intermédia e reduzida de cada região e dois exemplos
  de bens ou serviços por taxa. Usa uma tabela em Markdown."
- **T2.** "Os testes de IVA da Madeira falham. Descobre porquê e corrige."
- **T3.** "Acrescenta fatura/nif.py com valido(nif: str) -> bool, que valida um NIF português: 9 dígitos,
  prefixo permitido e dígito de controlo correto. Aceita espaços entre os dígitos. Escreve testes."
- **T4.** "Acrescenta fatura/totais.py com calcular(f: Fatura) -> Totais, sendo Totais um dataclass com:
  linhas (lista com o total de cada linha sem IVA: quantidade × preço × (1 − desconto), arredondado a
  2 casas por linha), por_taxa (dict taxa -> (base, iva), com o IVA calculado sobre a base de cada taxa e
  arredondado a 2 casas), sem_iva, iva e total. Usa Decimal e ROUND_HALF_UP. Escreve testes."
- **T5.** "Acrescenta fatura/io.py com para_json(f) e de_json(texto), com os valores decimais como
  strings, e um comando `python -m fatura total ficheiro.json` que imprime 'Total: 1 234,56 €'
  (espaço como separador de milhares, vírgula decimal)." O prompt inclui o formato JSON exato.
- **T6.** "Um cliente reportou que a nota de crédito parcial da fatura FT 2026/31 (exemplos/ft-2026-31.json,
  creditar 3 unidades da linha 2) dá um total 1 cêntimo abaixo do devido. Descobre a causa e corrige
  sem mudar o resto do comportamento." O módulo injetado usa `float` num único sítio subtil. A fatura
  do exemplo é do continente, para não depender da T2.
- **T7.** "Acrescenta fatura/reconciliacao.py com reconciliar(movimentos, faturas) …" com a especificação
  completa no prompt:
  - movimentos com NIF casam com uma ou várias faturas desse cliente (pagamento agregado), ou pagam
    parte de uma fatura, mas só quando não há combinação exata;
  - uma fatura paga com desconto de pronto pagamento de exatamente 2% (arredondado ao cêntimo) conta
    como liquidada;
  - diferenças até 0,01 € contam como exatas;
  - entre várias combinações possíveis, ganha a que liquida mais faturas por inteiro; em empate, a das
    faturas com vencimento mais antigo;
  - movimentos sem NIF só casam com uma fatura única com esse valor (com ou sem desconto);
  - por movimento, devolve as faturas, o valor aplicado a cada uma, o desconto usado e uma explicação
    curta em português;
  - tem de correr em menos de 2 s com 60 faturas em aberto e 30 movimentos.
- **T8.** "Escreve um email curto e cordial, em português de Portugal, para a Pastelaria Aurora, Lda. a
  explicar que a transferência de 1 234,56 € recebida a 3 de outubro liquidou as faturas FT 2026/14
  (612,40 €) e FT 2026/15 (634,86 €), esta última com desconto de pronto pagamento de 2%."
  As contas foram verificadas: 634,86 × 0,98 = 622,16 e 612,40 + 622,16 = 1 234,56.

### 2.3 Aceitação escondida e solução de referência

- `pilot/fatura/acceptance/test_tN.py`: um módulo por tarefa. **Vive fora das cópias de trabalho** e corre
  com o Python do braço: `python -m pytest <caminho absoluto>` na pasta do braço.
  Os testes afirmam factos e não forma. Por exemplo, a T7 verifica que a solução respeita as regras e
  que o objetivo é o ótimo conhecido, não que o texto da explicação é igual ao meu.
  - T1: as 9 taxas presentes (continente 23/13/6, Madeira 22/12/**4** (desde 1 out 2024, DLR 6/2024/M), Açores 16/9/4),
    e há uma tabela.
  - T2: as 9 taxas certas em `TAXAS`.
  - T3: NIFs válidos (ex.: 123456789) e inválidos (controlo errado, 8 ou 10 dígitos, letras, prefixos 0 e 4).
  - T4: 4 faturas com totais calculados à mão, incluindo arredondamento de .xx5, desconto de 12,5% e
    várias taxas.
  - T5: ida e volta igual, saída exata do CLI, decimais nunca em float.
  - T6: o cêntimo certo no caso reportado, e os outros casos da nota de crédito sem alteração.
  - T7: casos construídos com ótimo único, incluindo agregados, parciais, desconto, tolerância, movimento
    sem NIF ambíguo (não casa) e um teste de tempo com 60×30.
  - T8: menciona FT 2026/14, FT 2026/15, o montante e os 2%.
- `pilot/fatura/reference/`: a minha solução completa das 8 tarefas, que é o oráculo da validação.

## 3. Execução: `jev pilot`

```
jev pilot preflight                                  # ~$0,01: valida o avaliador e mostra a escada do Jev
jev pilot run --max-usd 4.5 --max-min 40 [--judge-usd 1]
jev pilot judge <id>                                 # pode repetir-se sem voltar a correr os braços
```

### 3.1 Preflight (antes de gastar)

1. **Oráculo e nulo, $0.** Ponto de partida + referência conclui 8/8 tarefas. O ponto de partida
   sozinho conclui 0/8: por exemplo, tem 8 das 9 taxas certas, mas a T2 só conta quando estão as 9.
   O teste de tempo da T7 tem de passar com folga na referência (< 0,5 s), para não ser instável.
2. **Juiz, poucos cêntimos.** Dois projetos iguais → empate. Referência vs. ponto de partida → ganha a
   referência. Textos de lixo → perdem.
3. **Escada do Jev, ~$0,01.** As 8 tarefas com `--dry` (paga-se só a decisão do Jev), para vermos o que
   ele escolhe antes de pagar a execução.

Se o passo 1 ou o 2 falharem, o piloto não arranca.

### 3.2 Corrida

- `pilot-runs/<id>/{standard,jev}/` são cópias do ponto de partida, com `git init`, commit inicial e
  `uv sync` feitos **antes** de o relógio começar.
- **Intercalado, tarefa a tarefa**, com a ordem dos braços a alternar (T1: standard primeiro; T2: jev
  primeiro; …), para anular efeitos de ordem e de hora do dia.
- **Envelope por braço, igual nos dois:** cada braço avança enquanto tiver tempo e dinheiro. As tarefas
  que sobram ficam "não iniciadas (envelope)".
- **Hermético:** os dois braços correm com `claude -p --restricted --strict-mcp-config
  --permission-prompts none --permission-mode acceptEdits`, com `--tools Read,Grep,Glob,Edit,Write,Bash`
  e `--allowed-tools "Bash(uv run pytest:*)"`. O `--restricted` ignora as settings do utilizador e
  confina as ferramentas de ficheiros à pasta do braço. Por isso o standard passa `--model opus
  --effort xhigh` explicitamente, que são os defeitos do utilizador. Isto é verificado por probe na
  implementação: pytest corre, outros comandos são negados, ler fora da pasta é negado.
- **Teto de custo por execução:** `--max-budget-usd` = o que sobra do envelope do braço.
- **Teto de tempo por execução:** timeout = minutos que sobram do envelope. Um `claude -p` morto não
  reporta custo, por isso corre com `--output-format stream-json` e o harness soma o uso mensagem a
  mensagem; ao matar, fica com o custo até ali.
- **Braço jev:** o Jev decide. Se escolhe Anthropic, corre o mesmo comando com o `--model` e o `--effort`
  dele. Se escolhe um modelo barato, corre num free (Nemotron Ultra, via litellm). Se escolhe barato numa
  tarefa de ficheiros, corre no haiku com o esforço dele. **O custo de cada decisão do Jev conta no
  envelope do braço jev.** Se uma execução falhar, repete no standard e gasta do envelope do JEV. Se o
  Jev classificar mal uma tarefa de código como texto, ela vai para um free, fica entregue só em texto e
  chumba na aceitação. É informação sobre o Jev.
- **Tarefas de texto:** o harness grava a resposta final no ficheiro de saída, nos dois braços.
- **Depois de cada execução:** corre a aceitação dessa tarefa, faz commit "após Tn" na cópia do braço e
  regista.

### 3.3 Registo

Fica num ficheiro próprio, `$JEV_HOME/pilots/<id>.jsonl`, separado do ledger do dia a dia, porque a
semântica é diferente (os dois lados são medidos e os dois podem falhar). Tipos de linha:

- `meta`: envelopes, data e hash do ponto de partida;
- `task`: uma por braço por tarefa, com `status` (done | failed | timeout | budget | skipped), decisão
  do JEV, `model_id`, fallback, custo, `wall_ms`, tokens e aceitação;
- `final`: uma por braço, com a aceitação final de todas as tarefas sobre o estado final (apanha
  regressões), performance e higiene;
- `judge`: os veredictos e o custo do juiz.

## 4. Avaliação

### 4.1 Objetiva, feita pelo harness sobre o estado final

| Dimensão | Medida |
|---|---|
| Conclusão | tarefas cuja aceitação passa toda, no estado final, de 8 |
| Custo | soma por braço; **custo por tarefa concluída** |
| Tempo | soma de `wall_ms` por braço e por tarefa |
| Performance | T7 com 60×30 e T4 com 10k linhas, mediana de 3 execuções (só se a tarefa estiver concluída) |
| Higiene | `uvx ruff check` (número de avisos); testes do próprio agente a passar; deteção de não-alterações (status done sem diff) |

### 4.2 Juiz LLM, para o que os testes não veem

- **Juiz:** Opus 5.5 (`claude -p --model opus --effort high --tools ""`). Os modelos free ficam de fora:
  não decidem nada, e julgar é decidir. O juiz recebe **o mesmo material** dos dois lados: o código-fonte dos dois projetos (sem `.venv` nem `.git`) e os textos,
  rotulados só "Projeto A" e "Projeto B", com as tarefas e os critérios. O material é tratado como dados
  e não como instruções.
- **Par-a-par às cegas:** o juiz avalia duas vezes, com A/B trocados, o que dá 2 veredictos por critério.
  Respostas possíveis: A, B, empate, ambos maus, com o motivo em ≤ 2 frases. A resposta é JSON
  estruturado.
- **Critérios**, escritos como afirmações verificáveis:
  1. **Legibilidade:** nomes claros, funções com um propósito, sem código morto nem duplicado.
  2. **Robustez:** valida inputs, os erros dizem o campo em causa, nunca há float em dinheiro.
  3. **Testes do agente:** cobrem os casos-limite que importam (arredondamento, NIF inválido,
     reconciliação ambígua).
  4. **Desenho da reconciliação (T7):** o algoritmo é adequado ao tamanho, as regras de desempate
     estão explícitas e as explicações são úteis.
  5. **Textos (T1, T8):** exatos, claros, em pt-PT, com o tom certo.
  - Considerados e deixados de fora: "eficiência" (já medida no benchmark) e "documentação do código"
    (sobrepõe-se a legibilidade).
- **Agregação:** se os 2 veredictos concordam, é esse. Se o vencedor muda com a ordem, o critério fica
  **inconclusivo**.

### 4.3 Veredicto final (regra por defeito, ajustável)

1. Ganha quem concluir mais tarefas dentro do envelope.
2. Em empate, ganha o menor custo por tarefa concluída.
3. O juiz não decide: qualifica. Por exemplo, "o JEV ganhou em custo, mas perdeu em robustez 3–1".

## 5. Dashboard: vista Piloto

- `GET /api/pilots` devolve os pilotos lidos de `$JEV_HOME/pilots/*.jsonl`.
- A vista mostra:
  - o envelope e as datas;
  - o **scorecard lado a lado**: conclusão x/8, custo, tempo, custo por tarefa concluída, performance,
    ruff, testes próprios;
  - **custo e tempo acumulados por tarefa contra o envelope**, dois gráficos em degraus com uma linha
    por braço;
  - uma tabela por tarefa: escolha do JEV, estado por braço (✓ ✗ ⏱ 💸 —), custo e tempo;
  - uma tabela do juiz: critério × 2 veredictos, com os motivos no hover.
- Estende a página atual, com a mesma linguagem visual e as mesmas garantias: 127.0.0.1, CSP, sem CDNs.

## 6. Orçamento por defeito

| | |
|---|---|
| Envelope por braço | $4,50 e 40 min (definido por ti ao lançar) |
| Juiz | $1 (Opus, duas passagens) |
| Decisões do Jev | ~$0,01 (8 tarefas + pré-voo; já contam no envelope do braço jev) |
| Probes e validação | < $0,20 |
| **Total** | **≤ $10** |

## 7. Testes do harness

Em TDD, com falsos só nas fronteiras externas:

- contabilidade dos envelopes: tempo e custo esgotados levam a tarefas não iniciadas;
- ordem intercalada e alternada;
- custo parcial a partir do `stream-json`, com uma fixture capturada de uma execução real;
- corredor da aceitação (oráculo e nulo sobre a referência real, $0);
- agregação do juiz: mapear veredictos com a ordem trocada e detetar inconclusivos;
- registo do piloto;
- `/api/pilots`.

Probe real (~$0,03): o modo hermético com pytest permitido e o resto negado.

## 8. Riscos e limitações

- **n = 1 por braço:** é um caso, não uma estatística.
- **O Jev exclui hoje o Fable** ("model_exclusion" nos testes de 2026-10-11), por isso a T7 deve ir para
  o Opus. O pré-voo mostra-o antes de gastar.
- **Viés do juiz** (o Opus a preferir o braço só-Opus): mitigado com as cegas e a troca de ordem. Não há
  segundo juiz de outra família, porque os free não decidem; um segundo juiz pago custaria mais.
- **Testes escondidos à medida da minha referência:** mitigado ao afirmar factos e não forma, e com a
  validação oráculo/nulo.
- **Rate limits dos modelos free:** no braço jev, uma execução free que falha repete no standard e gasta
  mais envelope. Fica registado.
- **O `--restricted` muda o standard de "as settings do utilizador" para "os mesmos valores, passados
  explicitamente"**, o que é equivalente para modelo e esforço. Hooks e CLAUDE.md do utilizador não
  entram em nenhum dos braços.
