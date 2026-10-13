# Manual do JEV

Como usar o JEV nas tuas sessões do Claude Code. O README explica como funciona por dentro e os pilotos.

## O que faz

O Jev da TypeSafe decide, em cada prompt que escreves, o modelo e o esforço:
- nas tarefas claras manda para o Sonnet;
- nas difíceis manda para o Opus, com menos esforço do que o standard (opus · xhigh).

Tudo corre pela tua subscrição.

Nos pilotos, isto custou 36% a 53% menos do que o standard, acabou mais depressa e passou as mesmas tarefas. O juiz preferiu o código do standard em alguns critérios.

Se alguma coisa falhar (o Jev, a rede, uma resposta estranha), o prompt corre no standard, como se o JEV não existisse.

## Instalar (uma vez por máquina)

```bash
uv tool install git+https://github.com/luistorresbarbosa-ltbsw/claudecode-turbo   # o núcleo: o comando jev
claude plugin marketplace add luistorresbarbosa-ltbsw/claudecode-turbo
claude plugin install jev@claudecode-turbo
```

Depois, dentro do Claude Code, `/plugin configure jev@claudecode-turbo` e cola a chave do OpenRouter. Em
alternativa, define `OPENROUTER_API_KEY` no teu ambiente.

## Usar

Abre o Claude Code como sempre (`claude`, em qualquer projeto). Todas as sessões passam pelo JEV.

| Para | Faz |
|---|---|
| Usar a v4 numa sessão | `JEV_POLICY=v4 claude` (ver "Que versão usar") |
| Desligar o JEV | `claude plugin disable jev@claudecode-turbo` (e `enable` para voltar) |
| Atualizar | `uv tool upgrade jev` e `claude plugin update jev@claudecode-turbo` |

Para desenvolver o próprio JEV, a partir de uma cópia do repositório:
`JEV_BIN="$PWD/.venv/bin/jev" claude --plugin-dir "$PWD/mod/jev"`, depois de `uv sync`.

## Que versão usar

| Versão | O que faz | Quando |
|---|---|---|
| **v3** (por defeito) | Uma faixa por tarefa: segue o Jev numa tarefa nova e mantém o modelo nos seguimentos, para não reescrever a cache. | Em geral, e nos repositórios de trabalho. |
| v4 (`JEV_POLICY=v4`) | A v3, mais duas coisas: <br>• os seguimentos curtos ("corre os testes", "sim, avança") não esperam pelo Jev; <br>• onde o Jev pede Opus com pouco ganho, corre sonnet · high. | Quando o custo pesa mais. Na corrida final custou 35% menos e passou as mesmas tarefas, mas o juiz preferiu o código da v3 no calc. |

As variáveis lêem-se quando a sessão arranca. Para mudar de versão, abre uma sessão nova.

## A linha de estado

| Mostra | Quer dizer |
|---|---|
| `JEV: a decidir…` | O Jev está a escolher (1 a 3 s). |
| `JEV: sonnet · medium` | O turno corre neste modelo e esforço. |
| `JEV: sonnet · medium · 17.3 s · poupado $0.1340 (64.9%)` | Fim do turno: o tempo que esperaste e o total poupado contra o standard. |
| `JEV: sem decisão, segue o standard` | O Jev falhou, e o prompt corre em opus · xhigh. |

## O que passa pelo Jev e o que não passa

- **Passam:** os prompts que escreves no terminal, os enviados pelo telemóvel (Remote Control) e os do `claude -p`.
- **Subagentes:** o Jev escolhe o modelo de cada um a partir da tarefa do agente.
  - Um fork herda o modelo.
  - Um subagente que já pede um modelo mais barato fica com o seu.
- **Não passam:** os comandos começados por `/` e as notificações. Correm no modelo da faixa atual.
- **Compactação:** depois de uma (manual ou automática), o Jev volta a escolher à vontade, porque a cache ficou fria.

## Mandar tu

- **Fixar o modelo:** escreve `/model opus` (ou outro). Daí em diante, essa sessão deixa de passar pelo Jev. Para voltar ao JEV, abre uma sessão nova.
- **Trabalho crítico** (uma migração delicada, uma revisão importante): fixa o modelo, ou abre essa sessão sem o JEV.

## Ver quanto custou

- **Resumo:** num terminal, `jev ledger`. Dá as tarefas, o custo do JEV contra o standard e o total poupado.
- **Dashboard:** `jev-dashboard --open`. Só funciona na máquina onde corre, em 127.0.0.1.
- **Onde fica tudo:** os registos ficam em `~/.jev/ledger.jsonl`, um por turno, com o modelo, o esforço, os tokens, o custo e o tempo. Também guardam quanto levou a decisão do Jev (`decide_ms`) e o `jev route` inteiro (`route_ms`).
- **O que custa o Jev:** cada decisão custa frações de cêntimo no OpenRouter. A chave tem um teto de $5, e até agora gastou-se $0.90.

Os custos são a preço de lista. Numa subscrição medem quota, não faturação.

## Privacidade

Em cada decisão, vão para o OpenRouter (o Jev da TypeSafe):
- o teu prompt (num subagente, a tarefa que o Claude lhe escreve);
- a troca anterior: o teu pedido anterior e o fim da resposta, até 2000 caracteres cada.

O resto do código do projeto não vai, só o que estiver nesses textos.

**Nos repositórios de trabalho, confirma antes que a empresa permite enviar isto a um serviço externo.**

Os modelos free (respostas fora da Anthropic) estão desligados por defeito. `JEV_POOL=all` liga-os, mas nos pilotos falharam no código.

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| Fica sempre em `sem decisão, segue o standard` | Testa o Jev à mão: `echo "explica o que é uma closure" \| jev route` deve devolver um JSON com `decision`. Um `router_error` a dizer que falta a chave: configura-a (ver "Instalar"). |
| O prompt demora mais 1 a 3 s a começar | É a decisão do Jev. Na v4, os seguimentos curtos não esperam. |
| Escolheu um modelo fraco para uma tarefa difícil | Fixa com `/model opus` nessa sessão. Se se repetir, guarda o prompt: serve para afinar. |
| Não aparece nada na linha de estado | O plugin não está instalado ou está desligado: `claude plugin list`. |
| `JEV: o núcleo não arrancou` | Falta o comando `jev`: corre o `uv tool install` de "Instalar". |

## Rever ao fim de uma semana

Abre uma sessão do Claude Code numa cópia deste repositório e pede, por exemplo:

> "Analisa o meu ledger do JEV desta semana: quanto poupei, onde trocou de modelo e quanto isso custou em cache, e se a v3 ou a v4 me teria servido melhor. Usa o simulador nas mesmas condições."

O ledger e os transcripts das tuas sessões chegam para isso. Não é preciso voltar a chamar o Jev.
