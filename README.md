# JEV

Um mod do Claude Code em que um modelo **gratuito** do OpenRouter decide, para cada tarefa, onde
ela corre: num modelo Anthropic (e com que esforço) ou num modelo free. Depois corre-a e mostra
quanto poupaste face ao teu Claude Code standard.

```
/jev corrige o typo no README
JEV → haiku · low · correção simples num ficheiro específico
...
custo JEV $0.0307 · standard opus · xhigh $0.1178 (estimado) · poupaste $0.0870
```

## Como funciona

1. **Decidir:** `nvidia/nemotron-3-super-120b-a12b:free` lê a tarefa e escolhe
   `anthropic` (`haiku | sonnet | opus | fable` × `low … max`) ou `openrouter-free`
   (Nemotron Ultra, Nemotron Super ou Gemma 4, só para texto que não toca no repo).
2. **Executar:** os modelos Anthropic correm com `claude -p`, pela **tua subscrição**. Os free
   correm via litellm, a $0.
3. **Comparar:** o custo real contra o **standard**, o modelo por defeito com o teu `effortLevel`.
   O standard é *medido* quando correu de facto e *estimado* quando se aplicam os mesmos tokens ao
   preço do Opus.
4. **Registar:** uma linha por tarefa em `~/.jev/ledger.jsonl`, que o dashboard lê.

**Fallback:** se o cérebro free falhar, a decisão passa a ser o standard. Se a execução escolhida
falhar, a tarefa repete no standard e o ledger soma as duas tentativas, porque uma execução
falhada também custa.

## Uso

```bash
uv sync
echo 'OPENROUTER_API_KEY=sk-or-...' > .env
```

No Claude Code (o mod está em `mod/jev`):

```bash
claude --plugin-dir /Users/luisbarbosa/Developer/repos/personal/claude-mods-jev/mod/jev
```

| Comando | O que faz |
|---|---|
| `/jev <tarefa>` | decide, corre só com leitura e regista |
| `/jev --edits <tarefa>` | deixa editar ficheiros (`acceptEdits`) |
| `/jev --ab <tarefa>` | corre também o standard, para medir a diferença a sério (gasta o dobro) |
| `/jev --dry <tarefa>` | só decide e estima, sem gastar quota |
| `/jev --ledger` | totais acumulados |

Fora do Claude Code: `uv run jev run "<tarefa>"`, `uv run jev ledger`.

Dashboard (local, só em 127.0.0.1):

```bash
uv run jev-dashboard --open
JEV_HOME=dashboard/demo uv run jev-dashboard --open   # com dados de demonstração
```

## Garantias e limites

- **Só leitura por defeito.** O `claude -p` corre com `--tools Read,Grep,Glob`, ou seja, sem
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

Variáveis: `JEV_HOME`, `JEV_MAX_USD`, `JEV_STANDARD_MODEL` (por defeito `opus`) e
`JEV_STANDARD_EFFORT` (por defeito `xhigh`).

## Desenvolvimento

```bash
uv run pytest               # núcleo + dashboard (os testes nunca saem para a internet)
claude plugin test mod/jev  # o mod
```
