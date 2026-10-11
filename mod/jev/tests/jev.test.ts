import type { CommandRunResult, On, ProcessRunInit, ProcessRunResult } from 'claude-code'
import type { Engine } from 'claude-code/testing'
import { expect, test } from 'claude-code/testing'

const REPORT = 'JEV → haiku · low · edição trivial\n\nCorrigido.\n\ncusto JEV $0.0227 · standard opus · xhigh $0.0881 (estimado) · poupaste $0.0654'
const RUN_JSON = JSON.stringify({
  ok: true,
  answer: 'Corrigido.',
  report: REPORT,
  decision: { runner: 'anthropic', model: 'haiku', effort: 'low' },
  summary: { tasks: 3, saved_usd: 0.4185, saved_pct: 14.3 },
})

type Call = { argv: readonly string[]; init?: ProcessRunInit }

function reply(stdout: string, exitCode = 0, stderr = ''): ProcessRunResult {
  return { exitCode, stdout, stderr, isStdoutTruncated: false, isStderrTruncated: false }
}

// O núcleo Python é a fronteira externa: o teste responde por ele, por baixo do plugin,
// e regista a linha de estado. As operações do motor respondem { value } (ou { deny }).
function engine(on: On, result: ProcessRunResult): { calls: Call[]; status: (string | undefined)[] } {
  const calls: Call[] = []
  const status: (string | undefined)[] = []
  on('process.run', (_$, e) => {
    calls.push(e)
    return { value: result }
  })
  on('ui.status', (_$, e) => {
    status.push(e.text)
    return { value: undefined }
  })
  return { calls, status }
}

// Como a pessoa a escrever /jev <args> no terminal.
function jev($: Engine, args: string): Promise<CommandRunResult> {
  return $.command.run({ command: 'jev', args, origin: { kind: 'composer' },
                         presentation: { isFullscreen: false, columns: 80 } })
}

// A única chamada ao cli: falha se houver zero ou mais do que uma.
function only(calls: Call[]): Call {
  expect(calls).toHaveLength(1)
  return calls[0]!
}

test('sem tarefa mostra o uso e não corre nada', async ($, on) => {
  const { calls } = engine(on, reply(RUN_JSON))

  const r = await jev($, '')

  expect(r.text).toContain('uso: /jev')
  expect(calls).toHaveLength(0)
})

test('a tarefa vai pelo stdin e a resposta é o relatório do JEV', async ($, on) => {
  const { calls, status } = engine(on, reply(RUN_JSON))

  const r = await jev($, 'corrige o typo no README')

  expect(r.text).toBe(REPORT)
  expect(only(calls).argv.slice(-3)).toEqual(['jev', 'run', '--json'])
  expect(only(calls).init?.stdin).toBe('corrige o typo no README')
  expect(only(calls).init?.timeoutMs).toBe(600_000)
  expect(status[status.length - 1]).toContain('haiku')
})

test('as flags do JEV passam para o cli e o resto é a tarefa', async ($, on) => {
  const { calls } = engine(on, reply(RUN_JSON))

  await jev($, '--edits --ab escreve testes para o ledger')

  expect(only(calls).argv).toContain('--edits')
  expect(only(calls).argv).toContain('--ab')
  expect(only(calls).init?.stdin).toBe('escreve testes para o ledger')
})

test('um traço que não é flag do JEV fica na tarefa e nunca entra no argv', async ($, on) => {
  const { calls } = engine(on, reply(RUN_JSON))

  await jev($, '--help explica isto')

  expect(only(calls).argv).not.toContain('--help')
  expect(only(calls).init?.stdin).toBe('--help explica isto')
})

test('uma tarefa que falhou ainda mostra o relatório (o cli sai com 1 mas escreve o JSON)', async ($, on) => {
  engine(on, reply(RUN_JSON, 1))

  const r = await jev($, 'x')

  expect(r.text).toBe(REPORT)
})

test('se o cli não devolver JSON mostra o erro e limpa a linha de estado', async ($, on) => {
  const { status } = engine(on, reply('', 1, 'Traceback (most recent call last): boom'))

  const r = await jev($, 'x')

  expect(r.text).toContain('JEV falhou')
  expect(r.text).toContain('boom')
  expect(status[status.length - 1]).toBe(undefined)
})

test('--ledger mostra os totais acumulados', async ($, on) => {
  const { calls } = engine(on, reply('12 tarefas · poupado $0.4200 (14%)\n'))

  const r = await jev($, '--ledger')

  expect(only(calls).argv.slice(-2)).toEqual(['jev', 'ledger'])
  expect(r.text).toBe('12 tarefas · poupado $0.4200 (14%)')
})

test('--dry mostra a decisão e a estimativa (o JSON do dry não traz totais)', async ($, on) => {
  const dry = JSON.stringify({
    decision: { runner: 'openrouter-free', model: 'nvidia/nemotron-3-ultra-550b-a55b:free', effort: null },
    estimate: { jev_usd: 0, standard_usd: 0.0832 },
    report: 'JEV → nemotron (free) · pergunta conceptual\nestimativa: JEV $0.0000 · standard $0.0832 (não correu)',
  })
  const { calls, status } = engine(on, reply(dry))

  const r = await jev($, '--dry o que é um monad?')

  expect(only(calls).argv).toContain('--dry')
  expect(r.text).toContain('estimativa')
  expect(status[status.length - 1]).toContain('nemotron-3-ultra')
})
