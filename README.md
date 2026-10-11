# JEV

Um mod do Claude Code em que o **Jev da TypeSafe** (`typesafe/jev-router`, via OpenRouter) decide
**cada prompt que escreves e cada subagente**: corre num modelo **Anthropic, pela tua subscrição**,
com o modelo e o esforço que ele escolher, ou, nas tarefas simples, num **modelo free**. Modelos mais
leves e menos esforço respondem mais depressa, e o JEV mede o custo e a velocidade de cada turno
contra o teu Claude Code standard (opus · xhigh).

Não há comando: escreves como sempre. A linha de estado mostra a decisão, por exemplo
`JEV: sonnet · medium · 17.3 s · poupado $0.1340 (64.9%)`.

## Como funciona

1. **Decidir (o Jev, ~1-4 s, frações de cêntimo).** Ao enviares um prompt, o mod pergunta ao Jev
   (`jev route`). O Jev classifica a tarefa (tipo, dificuldade 0-4, ganho de um modelo maior) e escolhe
   o modelo mais barato que chega, com o esforço. O pool que lhe damos tem os modelos Anthropic e três
   baratos (`gpt-6-luna`, `gemini-*-flash`, `deepseek-*-flash`), que fazem de "free" porque os modelos
   free não estão no pool do Jev. Pedimos-lhe 1 token: a decisão vem nos metadados do OpenRouter.
   O Jev lê também a troca anterior (o teu último pedido e o fim da resposta). Sem ela, um
   seguimento como "sim, avança" parecia conversa e ia para um free.
2. **Executar.**
   - O Jev escolhe **Anthropic**: o mod reescreve o modelo e o esforço de cada pedido do turno
     (`turn.step`), e a sessão responde com eles, pela tua subscrição.
   - O Jev escolhe **um barato**: a tarefa é simples e responde um **free** (Nemotron Ultra), a $0. O
     prompt não gasta quota Anthropic, e a resposta fica na conversa para os turnos seguintes.
   - Barato numa tarefa que **mexe em ficheiros**: um free não tem ferramentas, por isso vai para o
     **sonnet**, com o esforço do Jev. (Ia para o haiku, mas no primeiro piloto o haiku falhou a
     maioria destas tarefas.)
   - **Subagentes:** o Jev decide com a tarefa do agente. O modelo vai na chamada `Agent` e o esforço
     nos passos do subagente. Um subagente nunca vai para um free (usa ferramentas).
   - Os modelos free só executam; nunca decidem.
3. **Registar (`jev record`).** No fim de cada turno: o custo real (preços via litellm, mais a decisão
   do Jev) e o tempo que esperaste (decisão + turno), contra o standard. Quando o Jev falha e a sessão
   segue no standard, esse turno fica como **medição real do standard**.
4. **Ver.** `uv run jev-dashboard --open` mostra o custo e a velocidade, JEV contra standard.

**Fallback:** se o Jev falhar (erro, timeout de 15 s, um modelo fora do pool) ou o free falhar, a
sessão segue com o standard, sem mudanças.

### Versões (`JEV_POLICY`)

- **v1** (por defeito): cada prompt corre no modelo e no esforço que o Jev escolher para ele.
- **v2**: o modelo e o esforço são da sessão.
  - **Porquê:** a cache do Claude é de cada modelo. Trocar de modelo a meio obriga a escrever a
    conversa toda na cache do novo modelo, a 2× o preço de entrada. Mudar o esforço invalida a cache
    das mensagens.
  - **Com a cache quente,** o modelo e o esforço só sobem: um modelo maior, ou mais esforço no mesmo
    modelo, porque aí a qualidade paga a reescrita.
  - **Com a cache fria,** vale a escolha do Jev: numa sessão nova, depois de um `/clear` ou de uma
    compactação, ou com mais de uma hora parada.
  - **Os turnos que não passam pelo Jev,** como uma notificação, ficam no modelo da sessão.
  - **O pool** fica só com modelos Anthropic, salvo `JEV_POOL=all`.
  - **Onde fica o modelo da sessão:** em `$JEV_HOME/sessions/<id>.json`, pelo id da sessão, para
    sobreviver a um `--resume`.

**No histórico do OpenRouter**, cada decisão aparece com o modelo que serviu o token (por exemplo
`gpt-6-luna` ou `claude-sonnet-5.5`) e com `router: typesafe/jev-router`.

## Uso

```bash
uv sync
echo 'OPENROUTER_API_KEY=sk-or-...' > .env
claude --plugin-dir /Users/luisbarbosa/Developer/repos/personal/claude-mods-jev/mod/jev
```

Dashboard (local, só em 127.0.0.1):

```bash
uv run jev-dashboard --open
JEV_HOME=dashboard/demo uv run jev-dashboard --open   # com dados de demonstração
```

Fora da sessão: `uv run jev ledger` (totais) e `uv run jev run "<tarefa>"`, que corre uma tarefa
avulsa num `claude -p` (`--edits`, `--ab`, `--dry`).

## Piloto

O mesmo projeto corre duas vezes, uma no Claude Code standard e outra com o JEV, com tetos de tempo e
de custo. No fim, um juiz Opus (pela subscrição) compara os dois resultados às cegas. A spec está em
`docs/superpowers/specs/2026-10-11-piloto-jev-design.md`.

```bash
uv run jev pilot run --project fatura --max-min 10 --max-usd-task 1 --max-usd-total 4.5
uv run jev pilot run --project fatura --anthropic-only   # pool do Jev só com modelos Anthropic
uv run jev pilot run --project fatura --arms jev-v1,jev-v2 --session   # v1 contra v2, uma sessão por braço
```

`--arms` escolhe os dois braços: `standard`, `jev` (a versão por defeito), `jev-v1` e `jev-v2`.
`--session` corre todas as tarefas de cada braço numa só sessão, com `claude -p --resume`. Cada tarefa
de código leva também um seguimento ("Corre os testes e corrige o que falhar."), como numa sessão a
sério. É assim que se vê o efeito da cache: com um prompt por sessão, a v1 e a v2 comportam-se igual.

`--no-judge` salta o juiz. `--claude-md` dá aos dois braços o mesmo CLAUDE.md, feito de
`pilot/<projeto>/regras.md` (no fatura, as críticas do juiz às primeiras corridas). O juiz não o lê:
é igual nos dois. O dashboard mostra o piloto na vista "Piloto", atualizada em direto.

Há dois projetos: `fatura` (faturação portuguesa) e `calc` (uma pequena linguagem de expressões, com
tarefas que vão de um bug de associatividade à inferência de tipos Hindley–Milner). Cada um tem as
tarefas (`tasks.json`), o ponto de partida (`seed/`), os testes escondidos (`acceptance/`), uma
solução de referência (`reference/`) e um `validate.py`, que confirma que o ponto de partida chumba
todas as tarefas e a referência passa todas. Um `juiz.json` diz ao juiz o que é o projeto e o que
cada critério quer dizer nele.

## Garantias e limites

- **Na sessão, o JEV só escolhe o modelo e o esforço:** as permissões e as ferramentas são as tuas.
- **`jev run` (tarefas avulsas) é só leitura por defeito.** O `claude -p` corre com `--tools Read,Grep,Glob`, ou seja, sem
  Bash. Um probe real confirmou que o `--permission-mode dontAsk` deixa correr Bash, por isso
  não é usado. Com `--edits` juntam-se `Edit` e `Write`. Nunca há `bypassPermissions`.
- **Só a subscrição.** O `claude -p` filho recebe o ambiente sem `ANTHROPIC_API_KEY` nem
  `ANTHROPIC_AUTH_TOKEN`, e o litellm está impedido de carregar o `.env` do projeto onde corres.
- **Teto por tarefa:** `--max-budget-usd` (`JEV_MAX_USD`, por defeito 0.50). É verificado depois
  de cada chamada, por isso trava execuções descontroladas mas não a primeira chamada.
- **Os custos são a preço de lista.** Numa subscrição medem consumo de quota, não faturação.
- **A estimativa é conservadora.** Não conta o thinking extra do standard (xhigh) nem o
  tokenizer maior do Opus. Para números a sério, usa `--ab`.
- **Preços:** vêm do litellm, com duas correções confirmadas contra o `total_cost_usd` do
  próprio Claude Code: a escrita de cache de 1h custa 2× o input, e o cache read do Sonnet 5.5
  é $0.20/M.

Variáveis: `JEV_HOME`, `JEV_MAX_USD`, `JEV_STANDARD_MODEL` (por defeito `opus`),
`JEV_STANDARD_EFFORT` (por defeito `xhigh`), `JEV_POOL` (`anthropic` deixa o pool do Jev só com
modelos Anthropic, sem respostas free; `all` mete os baratos) e `JEV_POLICY` (`v1` ou `v2`).

## Desenvolvimento

```bash
uv run pytest               # núcleo + dashboard (os testes nunca saem para a internet)
claude plugin test mod/jev  # o mod (simula prompts, turnos e subagentes)
```
