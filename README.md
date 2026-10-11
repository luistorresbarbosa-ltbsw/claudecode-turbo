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
```

`--no-judge` salta o juiz. O dashboard mostra o piloto na vista "Piloto", atualizada em direto.

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
`JEV_STANDARD_EFFORT` (por defeito `xhigh`) e `JEV_POOL` (`anthropic` deixa o pool do Jev só com
modelos Anthropic, sem respostas free).

## Desenvolvimento

```bash
uv run pytest               # núcleo + dashboard (os testes nunca saem para a internet)
claude plugin test mod/jev  # o mod (simula prompts, turnos e subagentes)
```
