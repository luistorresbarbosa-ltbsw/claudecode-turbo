import type { CommandRunResult, ProcessRunResult, Register } from 'claude-code'

// O núcleo do JEV é Python e vive no repositório; este mod é só a casca do /jev.
const REPO = '/Users/luisbarbosa/Developer/repos/personal/claude-mods-jev'
const CLI = ['uv', 'run', '--project', REPO, 'jev'] as const
const RUN_TIMEOUT_MS = 600_000 // o máximo do $.process.run; o cli corta o claude -p aos 590 s

const USAGE = [
  'uso: /jev [--edits] [--ab] [--dry] <tarefa>',
  '  --edits   deixa o modelo editar ficheiros (por defeito só lê)',
  '  --ab      corre também o standard, para medir a diferença a sério',
  '  --dry     só decide e estima: não corre nem gasta quota',
  '/jev --ledger   totais acumulados',
  `dashboard: uv run --project ${REPO} jev-dashboard --open`,
].join('\n')

type CliOutput = {
  report: string
  decision: { model: string; effort: string | null }
  summary?: { saved_usd: number; saved_pct: number } // ausente no --dry
}

// Separa as flags do JEV do início dos argumentos; o resto, tal como foi escrito, é a tarefa.
// A tarefa segue pelo stdin, por isso um "--help" dentro dela nunca chega ao argv do cli.
function parse(args: string): { flags: string[]; task: string; isLedger: boolean } {
  const flags: string[] = []
  let rest = args.trimStart()
  let isLedger = false
  for (;;) {
    const m = rest.match(/^(--(?:edits|ab|dry|ledger))(?:\s+|$)/)
    const flag = m?.[1]
    if (!m || !flag) break
    if (flag === '--ledger') isLedger = true
    else flags.push(flag)
    rest = rest.slice(m[0].length)
  }
  return { flags, task: rest.trim(), isLedger }
}

// O cli escreve o JSON mesmo quando a tarefa falha (sai com 1), por isso lê-se sempre.
function readCli(stdout: string): CliOutput | undefined {
  try {
    const out = JSON.parse(stdout)
    return typeof out?.report === 'string' ? out : undefined
  } catch {
    return undefined
  }
}

function failure(r: ProcessRunResult): string {
  const why = (r.stderr.trim() || r.stdout.trim()).slice(-600)
  return `JEV falhou (exit ${r.exitCode})${why ? `:\n${why}` : ''}`
}

function statusOf(out: CliOutput): string {
  const effort = out.decision.effort ? ` · ${out.decision.effort}` : ''
  const choice = `JEV: ${out.decision.model.split('/').pop()}${effort}`
  if (!out.summary) return `${choice} (dry)`
  return `${choice} · poupado $${out.summary.saved_usd.toFixed(4)} (${out.summary.saved_pct}%)`
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'jev',
      description: 'O JEV escolhe o modelo e o esforço, corre a tarefa e mostra quanto poupaste',
      argumentHint: '[--edits] [--ab] [--dry] <tarefa> | --ledger',
    })
    return next(e)
  })

  on('command.run', { command: 'jev' }, async ($, e): Promise<CommandRunResult> => {
    const { flags, task, isLedger } = parse(e.args)

    if (isLedger) {
      const r = await $.process.run([...CLI, 'ledger'], { timeoutMs: 60_000 })
      return { text: r.exitCode === 0 ? r.stdout.trim() : failure(r) }
    }
    if (!task) return { text: USAGE }

    $.ui.status('JEV: a decidir e a correr…')
    const r = await $.process.run([...CLI, 'run', '--json', ...flags], { stdin: task, timeoutMs: RUN_TIMEOUT_MS })
    const out = readCli(r.stdout)
    if (!out) {
      $.ui.status(undefined)
      return { text: failure(r) }
    }
    $.ui.status(statusOf(out))
    return { text: out.report }
  })
}
