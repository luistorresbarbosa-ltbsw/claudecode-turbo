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

function engine(on: On, routes: { route?: object; agent?: object; raw?: string }) {
  const calls: Call[] = []
  const status: (string | undefined)[] = []
  const appended: unknown[] = []
  const steps: TurnStepInput[] = []
  const agentCalls: { model?: string }[] = []
  on('process.run', (_$, e) => {
    calls.push(e)
    const out = e.argv.includes('record') ? { summary: { tasks: 2, saved_usd: 0.0571, saved_pct: 49.1 } }
      : e.argv.includes('--agent') ? routes.agent : routes.route
    const stdout = routes.raw ?? JSON.stringify(out)
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
  return { calls, status, appended, steps, agentCalls, records }
}

function typed($: Engine, text: string, kind: 'composer' | 'task-notification' = 'composer') {
  return $.prompt.submit({ text, origin: { kind } as never, wait: false } as never)
}

async function turn($: Engine, turnId: string, step: { model?: string; agentId?: string } = {}) {
  if (!step.agentId) await $.turn.start({ text: 'x', turnId })
  const stream = $.turn.step({ turnId, index: 0, model: step.model ?? 'claude-opus-5-5', effort: 'xhigh', messageCount: 1,
                               ...(step.agentId ? { agentId: step.agentId } : {}) } as never)
  for (;;) if ((await stream.next()).done) break
  return $.turn.complete({ answer: 'ok', durationMs: 4000, isAborted: false, turnId, reason: 'answer', usage: USAGE,
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

  expect(calls).toHaveLength(0)
  expect(steps[0]?.model).toBe('claude-opus-5-5')
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
})

test('um fork herda o modelo e não passa pelo Jev', async ($, on) => {
  const { calls, agentCalls } = engine(on, { agent: HAIKU_AGENT })

  await $.tool.call({ tool: 'Agent', description: 'x', prompt: 'y', subagent_type: 'fork' } as never)

  expect(calls).toHaveLength(0)
  expect(agentCalls[0]?.model).toBe(undefined)
})
