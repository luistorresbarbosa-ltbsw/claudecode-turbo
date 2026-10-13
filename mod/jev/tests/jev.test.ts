import type { On, ProcessRunInit, TurnStepInput } from 'claude-code'
import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'

// O que o `jev route` devolve (o núcleo Python é a fronteira externa: o teste responde por ele)
const SONNET_LOW = {
  decision: { runner: 'anthropic', model: 'sonnet', effort: 'low', rationale: 'Jev: code:repo_scan', is_standard: false },
  model_id: 'claude-sonnet-5-5', decide_ms: 1200, free: null,
}
const STANDARD = {
  decision: { runner: 'anthropic', model: 'opus', effort: 'xhigh', rationale: 'fallback', is_standard: true },
  model_id: null, decide_ms: 900, free: null,
}
const FREE = {
  decision: { runner: 'openrouter-free', model: 'nvidia/nemotron-3-ultra-550b-a55b:free', effort: 'high',
              rationale: 'Jev: qa_knowledge · barato: corre num free', is_standard: false },
  model_id: 'nvidia/nemotron-3-ultra-550b-a55b:free', decide_ms: 1000,
  free: { ok: true, text: 'Uma closure é uma função que lembra o seu âmbito.', model_id: 'nvidia/nemotron-3-ultra-550b-a55b:free', duration_ms: 3000 },
  summary: { tasks: 1, saved_usd: 0.0942, saved_pct: 100 },
}
const HAIKU_AGENT = {
  decision: { runner: 'anthropic', model: 'haiku', effort: 'low', rationale: 'Jev: code:repo_scan · subagente: haiku', is_standard: false },
  model_id: 'claude-haiku-4-5', decide_ms: 800, free: null,
}
const USAGE = { input_tokens: 2, output_tokens: 4, cache_read_input_tokens: 10738, cache_creation_input_tokens: 14262, model: 'claude-sonnet-5-5' }

type Call = { argv: readonly string[]; init?: ProcessRunInit }

function engine(on: On, routes: { route?: object; agent?: object; raw?: string; sequence?: string[];
                                  env?: Record<string, string>; missing?: boolean; delayMs?: number }) {
  const calls: Call[] = []
  const status: (string | undefined)[] = []
  const appended: unknown[] = []
  const steps: TurnStepInput[] = []
  const agentCalls: { model?: string }[] = []
  let inflight = 0
  let maxInflight = 0
  on('process.run', async (_$, e) => {
    calls.push(e)
    inflight++
    maxInflight = Math.max(maxInflight, inflight)
    if (routes.delayMs) await new Promise(r => setTimeout(r, routes.delayMs))
    inflight--
    if (routes.missing) throw new Error(`spawn ${e.argv[0]} ENOENT`)
    const out = e.argv.includes('record') ? { summary: { tasks: 2, saved_usd: 0.0571, saved_pct: 49.1 } }
      : e.argv.includes('--agent') ? routes.agent : routes.route
    const next = routes.sequence && !e.argv.includes('record') ? routes.sequence.shift() : undefined
    const stdout = routes.raw ?? next ?? JSON.stringify(out)
    return { value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('ui.status', (_$, e) => {
    status.push(e.text)
    return { value: undefined }
  })
  on('session.append', (_$, e) => {
    appended.push(e.message)
    return { value: { message: e.message, uuid: 'u1' } } as never
  })
  on('prompt.submit', (_$, e) => ({ text: e.text, origin: e.origin }))
  on('session.id', () => ({ value: 'sessao-1' }) as never)
  on('env.get', (_$, e) => ({ value: routes.env?.[e.name] }) as never)
  on('session.usage', () => ({ value: { context: { tokens: 54_321, window: 200_000 } } }) as never)
  on('session.compact', () => ({ messages: [{ role: 'user', text: 'resumo da conversa', toolUses: [] }] }) as never)
  on('turn.start', (_$, e) => ({ turnId: e.turnId }))
  on('turn.step', async function* (_$, e) {
    steps.push(e)
    return { turnId: e.turnId, index: e.index, answer: 'ok', toolUses: [], stopReason: 'end_turn', usage: null }
  })
  on('turn.complete', (_$, e) => ({ text: e.answer, usage: e.usage, reason: e.reason }))
  on('tool.call', { tool: 'Agent' }, (_$, e) => {
    agentCalls.push({ model: e.model })
    return { result: { content: 'feito' } as never }
  })
  const records = () => calls.filter(c => c.argv.includes('record')).map(c => JSON.parse(c.init?.stdin ?? '{}'))
  return { calls, status, appended, steps, agentCalls, records, maxInflight: () => maxInflight }
}

function typed($: Engine, text: string, kind: 'composer' | 'task-notification' = 'composer') {
  return $.prompt.submit({ text, origin: { kind } as never, wait: false } as never)
}

async function turn($: Engine, turnId: string,
                    step: { model?: string; agentId?: string; text?: string; answer?: string } = {}) {
  if (!step.agentId) await $.turn.start({ text: step.text ?? 'x', turnId })
  const stream = $.turn.step({ turnId, index: 0, model: step.model ?? 'claude-opus-5-5', effort: 'xhigh', messageCount: 1,
                               ...(step.agentId ? { agentId: step.agentId } : {}) } as never)
  for (;;) if ((await stream.next()).done) break
  return $.turn.complete({ answer: step.answer ?? 'ok', durationMs: 4000, isAborted: false, turnId, reason: 'answer', usage: USAGE,
                           ...(step.agentId ? { agentId: step.agentId } : {}) } as never)
}

test('o teu prompt é decidido pelo Jev e o turno corre no modelo e no esforço dele', async ($, on) => {
  const { steps, status, records } = engine(on, { route: SONNET_LOW })

  const entered = await typed($, 'onde está o timeout?')
  await turn($, 't1')

  expect(entered.text).toBe('onde está o timeout?')
  expect(steps[0]?.model).toBe('claude-sonnet-5-5')
  expect(steps[0]?.effort).toBe('low')
  const [rec] = records()
  expect(rec.duration_ms).toBe(5200) // o turno (4000) mais a decisão do Jev (1200): o tempo que esperaste
  expect(rec.scope).toBe('main')
  expect(rec.usage.model).toBe('claude-sonnet-5-5')
  expect(status[status.length - 1]).toContain('sonnet · low')
})

test('prompts que não escreveste não passam pelo Jev', async ($, on) => {
  const { calls, steps } = engine(on, { route: SONNET_LOW })

  await typed($, 'tarefa terminada', 'task-notification')
  await turn($, 't1')

  expect(calls.filter(c => c.argv.includes('route'))).toHaveLength(0)
  expect(steps[0]?.model).toBe('claude-opus-5-5')
})

// O custo de uma conversa é o de todos os turnos: os que não passam pelo Jev também ficam no registo, com o motivo
test('uma notificação fica no registo, sem decisão do Jev', async ($, on) => {
  const { records } = engine(on, { route: SONNET_LOW })

  await typed($, 'tarefa terminada', 'task-notification')
  await turn($, 't1')

  const [rec] = records()
  expect(rec.decision.signals).toEqual({ jev: 'sem decisão', rule: 'notificação' })
  expect(rec.decision.router_cost_usd).toBe(0)
  expect(rec.decision.model).toBe('sonnet') // o modelo que respondeu (USAGE)
  expect(rec.baseline).toBe('same') // na v1 corre no modelo por defeito: o JEV não mudou nada
})

test('na v3, uma notificação corre na faixa e conta como do JEV', async ($, on) => {
  const { records } = engine(on, { route: { ...SONNET_LOW, policy: 'v3' } })

  await typed($, 'acrescenta fatura/io.py')
  await turn($, 't1')
  await typed($, 'tarefa terminada', 'task-notification')
  await turn($, 't2')

  const second = records()[1]
  expect(second.decision.signals.rule).toBe('notificação')
  expect(second.baseline).toBeUndefined() // correu na faixa do Jev: compara-se com o standard
})

test('com o modelo fixado, os turnos ficam no registo como modelo fixado', async ($, on) => {
  const { records } = engine(on, { route: SONNET_LOW })

  await typed($, '/model sonnet')
  await typed($, 'acrescenta fatura/io.py')
  await turn($, 't1')

  const [rec] = records()
  expect(rec.decision.signals.rule).toBe('modelo fixado')
  expect(rec.baseline).toBe('same')
  expect(rec.task).toBe('acrescenta fatura/io.py')
})

test('quando o Jev falha a sessão segue com o standard, e o turno conta como medição do standard', async ($, on) => {
  const { steps, records } = engine(on, { route: STANDARD })

  await typed($, 'x')
  await turn($, 't1')

  expect(steps[0]?.model).toBe('claude-opus-5-5')
  expect(steps[0]?.effort).toBe('xhigh')
  expect(records()[0].decision.is_standard).toBe(true)
})

test('uma decisão free responde sem gastar um turno Anthropic', async ($, on) => {
  engine(on, { route: FREE })

  const result = await typed($, 'o que é uma closure?')

  expect(result.drop).toContain('Uma closure é uma função') // mostrada, e o prompt não entrou (drop)
  expect(result.text).toBe(undefined)
})

test('uma resposta ilegível do núcleo deixa o prompt seguir sem mudanças', async ($, on) => {
  const { steps } = engine(on, { raw: 'Traceback: boom' })

  const entered = await typed($, 'x')
  await turn($, 't1')

  expect(entered.text).toBe('x')
  expect(steps[0]?.model).toBe('claude-opus-5-5')
})

test('um subagente corre no modelo e no esforço que o Jev escolheu para a tarefa dele', async ($, on) => {
  const { agentCalls, steps, records } = engine(on, { agent: HAIKU_AGENT })

  await $.tool.call({ tool: 'Agent', description: 'analisar', prompt: 'analisa o módulo de faturação' } as never)
  await turn($, 't9', { agentId: 'a1', model: 'claude-haiku-4-5-20251001' })

  expect(agentCalls[0]?.model).toBe('haiku')
  expect(steps[0]?.effort).toBe('low')
  expect(steps[0]?.model).toBe('claude-haiku-4-5-20251001') // o modelo veio do tool.call; o passo só ganha o esforço
  expect(records()[0].scope).toBe('agent')
  expect(records()[0].session).toBe('sessao-1') // para o registo por sessão
  expect(records()[0].context).toBeUndefined()
})

test('um fork herda o modelo e não passa pelo Jev', async ($, on) => {
  const { calls, agentCalls } = engine(on, { agent: HAIKU_AGENT })

  await $.tool.call({ tool: 'Agent', description: 'x', prompt: 'y', subagent_type: 'fork' } as never)

  expect(calls).toHaveLength(0)
  expect(agentCalls[0]?.model).toBe(undefined)
})

test('o turno de um fork fica no registo como subagente', async ($, on) => {
  const { records } = engine(on, { agent: HAIKU_AGENT })

  await $.tool.call({ tool: 'Agent', description: 'x', prompt: 'revê o diff', subagent_type: 'fork' } as never)
  await turn($, 't9', { agentId: 'f1', model: 'claude-opus-5-5' })

  const [rec] = records()
  expect(rec.scope).toBe('agent')
  expect(rec.task).toBe('revê o diff')
  expect(rec.decision.signals).toEqual({ jev: 'sem decisão', rule: 'fork' })
})

test('um subagente declarado com um modelo que já chega fica no registo, sem poupança atribuída ao JEV', async ($, on) => {
  const { records } = engine(on, { agent: SONNET_LOW })

  await $.tool.call({ tool: 'Agent', description: 'procurar', prompt: 'onde está o timeout?', model: 'opus' } as never)
  await turn($, 't9', { agentId: 'a7', model: 'claude-opus-5-5' })

  const [rec] = records()
  expect(rec.decision.signals.rule).toBe('modelo declarado')
  expect(rec.baseline).toBe('same')
})

// Sem a troca anterior, o Jev lê "sim, avança" como conversa e manda-o para um free (sonda real, 2026-10-11)
test('o Jev decide cada prompt a ver a troca anterior: o teu último pedido e a resposta', async ($, on) => {
  const { calls } = engine(on, { route: SONNET_LOW })

  await typed($, 'acrescenta fatura/io.py')
  await turn($, 't1', { text: 'acrescenta fatura/io.py', answer: 'Proponho validar os campos. Avanço?' })
  await typed($, 'sim, avança')

  const routes = calls.filter(c => c.argv.includes('route'))
  const sent = (i: number) => {
    const { task, history } = JSON.parse(routes[i]?.init?.stdin ?? '{}')
    return { task, history }
  }
  expect(routes[0]?.argv).toContain('--json')
  expect(sent(0)).toEqual({ task: 'acrescenta fatura/io.py', history: [] })
  expect(sent(1)).toEqual({
    task: 'sim, avança',
    history: [{ role: 'user', content: 'acrescenta fatura/io.py' },
              { role: 'assistant', content: 'Proponho validar os campos. Avanço?' }],
  })
})

test('uma resposta free também conta como a troca anterior', async ($, on) => {
  const { calls } = engine(on, { route: FREE })

  await typed($, 'o que é uma closure?')
  await typed($, 'dá um exemplo')

  const second = JSON.parse(calls.filter(c => c.argv.includes('route'))[1]?.init?.stdin ?? '{}')
  expect(second.history).toEqual([{ role: 'user', content: 'o que é uma closure?' },
                                  { role: 'assistant', content: 'Uma closure é uma função que lembra o seu âmbito.' }])
})

// v2: o modelo é da sessão. O núcleo guarda-o pelo id da sessão (que sobrevive a um --resume e muda com /clear)
test('o route leva o id da sessão', async ($, on) => {
  const { calls } = engine(on, { route: SONNET_LOW })

  await typed($, 'acrescenta fatura/io.py')

  const payload = JSON.parse(calls.find(c => c.argv.includes('route'))?.init?.stdin ?? '{}')
  expect(payload.session).toBe('sessao-1')
  expect(payload.reset).toBe(false)
})

function compact($: Engine, trigger: 'manual' | 'precompute') {
  return $.session.compact({ trigger, messages: [{ role: 'user', text: 'x', toolUses: [] }] } as never)
}

test('depois de uma compactação, o prompt seguinte diz ao núcleo que a cache ficou fria', async ($, on) => {
  const { calls } = engine(on, { route: SONNET_LOW })

  await typed($, 'primeiro')
  await compact($, 'precompute') // só prepara: a conversa ainda não mudou
  await typed($, 'segundo')
  await compact($, 'manual')
  await typed($, 'terceiro')
  await typed($, 'quarto')

  const resets = calls.filter(c => c.argv.includes('route')).map(c => JSON.parse(c.init?.stdin ?? '{}').reset)
  expect(resets).toEqual([false, false, true, false]) // só o primeiro prompt depois da compactação
})

test('na v2, um turno que não passou pelo Jev (uma notificação) fica no modelo e no esforço da sessão', async ($, on) => {
  const { steps } = engine(on, { route: { ...SONNET_LOW, policy: 'v2' } })

  await typed($, 'acrescenta fatura/io.py')
  await turn($, 't1')
  await typed($, 'tarefa terminada', 'task-notification')
  await turn($, 't2')

  expect(steps[1]?.model).toBe('claude-sonnet-5-5') // sem isto, ia para o opus por defeito e reescrevia a cache
  expect(steps[1]?.effort).toBe('low')
})

test('na v1, um turno que não passou pelo Jev fica no modelo por defeito', async ($, on) => {
  const { steps } = engine(on, { route: SONNET_LOW })

  await typed($, 'acrescenta fatura/io.py')
  await turn($, 't1')
  await typed($, 'tarefa terminada', 'task-notification')
  await turn($, 't2')

  expect(steps[1]?.model).toBe('claude-opus-5-5')
})

test('na v2, se o núcleo falhar, o turno cai no standard e não no modelo da sessão', async ($, on) => {
  const { steps } = engine(on, { sequence: [JSON.stringify({ ...SONNET_LOW, policy: 'v2' }), 'Traceback: boom'] })

  await typed($, 'primeiro')
  await turn($, 't1')
  await typed($, 'segundo')
  await turn($, 't2')

  expect(steps[0]?.model).toBe('claude-sonnet-5-5')
  expect(steps[1]?.model).toBe('claude-opus-5-5') // a regra: qualquer falha cai no standard
})

// v3: o núcleo guarda o contexto e a última troca por sessão, para sobreviverem a um `claude -p --resume`
test('o record leva a sessão, a resposta e o contexto', async ($, on) => {
  const { records } = engine(on, { route: SONNET_LOW })

  await typed($, 'acrescenta fatura/io.py')
  await turn($, 't1', { text: 'acrescenta fatura/io.py', answer: 'Proponho validar os campos. Avanço?' })

  const [rec] = records()
  expect(rec.session).toBe('sessao-1')
  expect(rec.answer).toBe('Proponho validar os campos. Avanço?')
  expect(rec.context).toBe(54_321)
})

test('na v3, um turno sem decisão também fica na faixa da sessão', async ($, on) => {
  const { steps } = engine(on, { route: { ...SONNET_LOW, policy: 'v3' } })

  await typed($, 'acrescenta fatura/io.py')
  await turn($, 't1')
  await typed($, 'tarefa terminada', 'task-notification')
  await turn($, 't2')

  expect(steps[1]?.model).toBe('claude-sonnet-5-5')
})

test('na v4, um turno sem decisão também fica na faixa da sessão', async ($, on) => {
  const { steps } = engine(on, { route: { ...SONNET_LOW, policy: 'v4' } })

  await typed($, 'acrescenta fatura/io.py')
  await turn($, 't1')
  await typed($, 'tarefa terminada', 'task-notification')
  await turn($, 't2')

  expect(steps[1]?.model).toBe('claude-sonnet-5-5')
})

// Para medir o que a v4 poupa: quanto tempo levou o `jev route` inteiro e, dentro dele, a decisão do Jev
test('o record leva quanto tempo demoraram o route e a decisão', async ($, on) => {
  const { records } = engine(on, { route: SONNET_LOW })

  await typed($, 'onde está o timeout?')
  await turn($, 't1')

  const [rec] = records()
  expect(rec.decide_ms).toBe(1200)
  expect(typeof rec.route_ms).toBe('number')
  expect(rec.route_ms).toBeGreaterThanOrEqual(0)
})

test('um /model escrito por ti fixa o modelo: os prompts seguintes já não passam pelo Jev', async ($, on) => {
  const { calls } = engine(on, { route: SONNET_LOW })

  await typed($, '/model sonnet')
  await typed($, 'acrescenta fatura/io.py')

  expect(calls.filter(c => c.argv.includes('route'))).toHaveLength(0)
})

test('um subagente declarado com um modelo mais barato do que o do Jev sobe para o do Jev', async ($, on) => {
  const { agentCalls } = engine(on, { agent: SONNET_LOW })

  await $.tool.call({ tool: 'Agent', description: 'procurar', prompt: 'onde está o timeout?', model: 'haiku' } as never)

  expect(agentCalls[0]?.model).toBe('sonnet')
})

test('um subagente declarado com um modelo mais alto do que o do Jev fica com o seu', async ($, on) => {
  const { agentCalls } = engine(on, { agent: SONNET_LOW })

  await $.tool.call({ tool: 'Agent', description: 'rever', prompt: 'revê a migração', model: 'opus' } as never)

  expect(agentCalls[0]?.model).toBe('opus')
})

test('sem decisão do Jev (standard), o subagente corre em opus e não herda o modelo da faixa', async ($, on) => {
  const { agentCalls, records } = engine(on, { agent: STANDARD })

  await $.tool.call({ tool: 'Agent', description: 'x', prompt: 'analisa o módulo' } as never)
  await turn($, 't9', { agentId: 'a2', model: 'claude-opus-5-5' })

  expect(agentCalls[0]?.model).toBe('opus')
  expect(records()[0].decision.signals.rule).toBe('Jev sem resposta')
})

test('com o núcleo em falta, o subagente corre em opus, e um declarado fable não desce', async ($, on) => {
  const { agentCalls } = engine(on, { missing: true })

  await $.tool.call({ tool: 'Agent', description: 'x', prompt: 'analisa', model: 'haiku' } as never)
  await $.tool.call({ tool: 'Agent', description: 'y', prompt: 'analisa', model: 'fable' } as never)

  expect(agentCalls.map(c => c.model)).toEqual(['opus', 'fable'])
})

test('dois subagentes do mesmo modelo com esforços diferentes ficam cada um com o seu esforço', async ($, on) => {
  const HIGH = { ...SONNET_LOW, decision: { ...SONNET_LOW.decision, effort: 'high' } }
  const { steps } = engine(on, { agent: SONNET_LOW, sequence: [JSON.stringify(SONNET_LOW), JSON.stringify(HIGH)] })

  await $.tool.call({ tool: 'Agent', description: 'a', prompt: 'tarefa simples' } as never)
  await $.tool.call({ tool: 'Agent', description: 'b', prompt: 'tarefa difícil' } as never)
  await turn($, 't1', { agentId: 'a', model: 'claude-sonnet-5-5' })
  await turn($, 't2', { agentId: 'b', model: 'claude-sonnet-5-5' })

  expect(steps.map(s => s.effort)).toEqual(['low', 'high'])
})

// Publicado num marketplace: o núcleo é o `jev` instalado com `uv tool install`, e a chave vem da configuração
test('por defeito chama o jev instalado (no PATH)', async ($, on) => {
  const { calls } = engine(on, { route: SONNET_LOW })

  await typed($, 'onde está o timeout?')
  await turn($, 't1')

  expect(calls.map(c => c.argv[0])).toEqual(['jev', 'jev'])
})

test('JEV_BIN aponta para outro núcleo (o do repositório, nos pilotos)', async ($, on) => {
  const { calls } = engine(on, { route: SONNET_LOW, env: { JEV_BIN: '/repo/.venv/bin/jev' } })

  await typed($, 'onde está o timeout?')
  await turn($, 't1')

  expect(calls.map(c => c.argv[0])).toEqual(['/repo/.venv/bin/jev', '/repo/.venv/bin/jev'])
})

test('a chave do OpenRouter configurada no plugin vai para o núcleo', { options: { openrouter_api_key: 'sk-or-teste' } },
  async ($, on) => {
    const { calls } = engine(on, { route: SONNET_LOW })

    await typed($, 'onde está o timeout?')

    expect(calls[0]?.init?.env?.OPENROUTER_API_KEY).toBe('sk-or-teste')
  })

test('sem chave configurada, o núcleo usa a do ambiente', async ($, on) => {
  const { calls } = engine(on, { route: SONNET_LOW })

  await typed($, 'onde está o timeout?')

  expect(calls[0]?.init?.env?.OPENROUTER_API_KEY).toBeUndefined()
})

test('sem o núcleo instalado, o prompt segue sem mudanças e a linha de estado diz como o instalar', async ($, on) => {
  const { status, steps } = engine(on, { missing: true })

  const entered = await typed($, 'onde está o timeout?')
  await turn($, 't1')

  expect(entered.text).toBe('onde está o timeout?')
  expect(steps[0]?.model).toBe('claude-opus-5-5') // o modelo da sessão, sem mudanças
  expect(status.some(s => s?.includes('uv tool install'))).toBe(true)
})

test('o núcleo fala sempre em UTF-8 (no Windows, os acentos estragavam-se)', async ($, on) => {
  const { calls } = engine(on, { route: SONNET_LOW })

  await typed($, 'antes de avançar para alterações')
  await turn($, 't1')

  expect(calls.every(c => c.init?.env?.PYTHONIOENCODING === 'utf-8')).toBe(true)
})

test('seis subagentes lançados de uma vez não disparam mais de quatro decisões ao mesmo tempo', async ($, on) => {
  const { agentCalls, maxInflight } = engine(on, { agent: SONNET_LOW, delayMs: 20 })

  await Promise.all(Array.from({ length: 6 }, (_, i) =>
    $.tool.call({ tool: 'Agent', description: `t${i}`, prompt: `tarefa ${i}` } as never)))

  expect(agentCalls).toHaveLength(6)
  expect(agentCalls.every(c => c.model === 'sonnet')).toBe(true)
  expect(maxInflight()).toBe(4)
})

test('o jev route de um subagente espera no máximo 30 s', async ($, on) => {
  const { calls } = engine(on, { agent: SONNET_LOW })

  await $.tool.call({ tool: 'Agent', description: 'x', prompt: 'analisa' } as never)

  expect(calls.find(c => c.argv.includes('--agent'))?.init?.timeoutMs).toBe(30_000)
})
