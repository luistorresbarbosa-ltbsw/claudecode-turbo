import type { EngineInterface, ProcessRunInit, Register, TurnStepInput, TurnUsage } from 'claude-code'

// O núcleo do JEV é Python, instalado à parte com `uv tool install` (o `jev` fica no PATH). JEV_BIN aponta para
// outro, por exemplo o do repositório (`.venv/bin/jev`) nos pilotos e em desenvolvimento.
const INSTALL = 'uv tool install git+https://github.com/luistorresbarbosa-ltbsw/claudecode-turbo'
// O que se configura no plugin (`userConfig` do plugin.json)
type Options = { openrouter_api_key?: string; jev_command?: string }
// Prompts escritos pela pessoa: no terminal, pelo telemóvel (bridge) ou num `claude -p` (sdk)
const ROUTED_ORIGINS = new Set(['composer', 'bridge', 'sdk'])
type Effort = 'low' | 'medium' | 'high' | 'xhigh' | 'max'
type Model = 'haiku' | 'sonnet' | 'opus' | 'fable'
const RANK: Record<Model, number> = { haiku: 0, sonnet: 1, opus: 2, fable: 3 }

type Decision = {
  runner: 'anthropic' | 'openrouter-free'
  model: string
  effort: Effort | null
  rationale: string
  is_standard: boolean
}
type Summary = { tasks: number; saved_usd: number; saved_pct: number }
type Route = {
  decision: Decision
  policy?: 'v1' | 'v2' | 'v3' | 'v4'
  model_id: string | null
  decide_ms: number
  free: { ok: boolean; text: string; model_id: string; duration_ms: number } | null
  summary?: Summary
}
// waitMs: o que esperaste antes do turno; routeMs: o `jev route` inteiro, com o arranque do processo e o free
type Routed = { task: string; route: Route; waitMs: number; routeMs: number; scope: 'main' | 'agent' }
type Exchange = { prompt: string; answer: string }

let pending: Routed | undefined // decidido no prompt.submit, à espera do turn.start
const turns = new Map<string, Routed>() // turno principal -> decisão
const queuedAgents: Routed[] = [] // decididos no tool.call, à espera do 1.º passo do subagente
const agents = new Map<string, Routed>() // subagente -> decisão
// A última troca do turno principal (o pedido e a resposta): o Jev decide o prompt seguinte com ela.
// Sem ela, um seguimento como "sim, avança" parece conversa e ia para um free.
let lastExchange: Exchange | undefined
// Uma compactação reescreve a conversa: a cache do modelo fica fria e, na v2, o Jev volta a escolher à vontade.
// (Um /clear não precisa disto: a sessão continua com outro id, e o núcleo guarda o modelo pelo id.)
let resetPending = false
// Na v2, o modelo e o esforço da sessão: um turno que não passou pelo Jev (uma notificação) também corre neles,
// senão ia para o modelo por defeito e a cache reescrevia-se duas vezes (para lá e de volta)
let sessionModel: { model: string; effort: Effort | null } | undefined
// Um `/model` escrito por ti fixa o modelo: daí em diante a sessão não passa pelo Jev
let pinned = false
const prompts = new Map<string, string>() // turno principal -> o pedido com que começou

function history(): { role: 'user' | 'assistant'; content: string }[] {
  if (!lastExchange) return []
  return [{ role: 'user', content: lastExchange.prompt }, { role: 'assistant', content: lastExchange.answer }]
}

function readJson<T>(text: string): T | undefined {
  try {
    return JSON.parse(text) as T
  } catch {
    return undefined
  }
}

function label(d: Decision): string {
  if (d.is_standard) return 'standard'
  const model = d.model.split('/').pop() ?? d.model
  return d.effort ? `${model} · ${d.effort}` : model
}

function totals(s: Summary | undefined): string {
  return s ? ` · poupado $${s.saved_usd.toFixed(4)} (${s.saved_pct}%)` : ''
}

// O subagente chega ao 1.º passo com o modelo que lhe demos no tool.call: é por aí que se liga à decisão
function claimAgent(e: TurnStepInput): Routed | undefined {
  if (!e.agentId) return undefined
  const known = agents.get(e.agentId)
  if (known) return known
  const i = queuedAgents.findIndex(r => r.route.model_id !== null && e.model.startsWith(r.route.model_id))
  if (i < 0) return undefined
  const [routed] = queuedAgents.splice(i, 1)
  if (!routed) return undefined
  agents.set(e.agentId, routed)
  return routed
}

let opts: Options = {}
let bin: string | undefined
// Chama o núcleo; a chave configurada no plugin vai no ambiente dele (sem ela, vale a do teu ambiente)
async function jev($: EngineInterface, args: string[], init: ProcessRunInit) {
  bin ??= (await $.env.get('JEV_BIN')) || opts.jev_command || 'jev'
  // UTF-8 sempre: no Windows o Python lia o pipe em cp1252 e os acentos estragavam-se (avançar → avanÃ§ar)
  const env = { PYTHONIOENCODING: 'utf-8', ...(opts.openrouter_api_key ? { OPENROUTER_API_KEY: opts.openrouter_api_key } : {}) }
  return $.process.run([bin, ...args], { ...init, env })
}

// Os turnos que não passam pelo Jev também ficam no registo (o custo de uma conversa é o de todos os turnos),
// com o porquê; `same`: sem o JEV teriam corrido igual, por isso nada se atribui ao JEV
type Unrouted = { task: string; why: string; same: boolean; effort?: string | null; model?: string }
let unroutedPending: Unrouted | undefined
const unrouted = new Map<string, Unrouted>() // turno principal -> porquê
const queuedUnrouted: Unrouted[] = [] // subagentes lançados sem o Jev, à espera do 1.º passo
const unroutedAgents = new Map<string, Unrouted>() // subagente -> porquê
const ORIGIN_WHY: Record<string, string> = {
  'task-notification': 'notificação', 'scheduled-trigger': 'tarefa agendada', peer: 'outra sessão',
  'peer-send-message': 'outra sessão', 'projects-relay': 'outra sessão', channel: 'canal',
}
const alias = (id: string) => (['opus', 'sonnet', 'haiku', 'fable'] as const).find(k => id.includes(k)) ?? id

// No 1.º passo de um turno sem decisão: o esforço com que correu e, num subagente, a que lançamento pertence
function noteUnrouted(e: TurnStepInput, laneEffort: string | null | undefined) {
  const stepEffort = typeof e.effort === 'string' ? e.effort : null // um orçamento em tokens não é um nome de esforço
  if (!e.agentId) {
    const u = unrouted.get(e.turnId)
    if (u && u.effort === undefined) u.effort = laneEffort ?? stepEffort
    return
  }
  if (unroutedAgents.has(e.agentId)) return
  const i = queuedUnrouted.findIndex(u => !!u.model && e.model.includes(u.model))
  const [u] = queuedUnrouted.length ? queuedUnrouted.splice(i >= 0 ? i : 0, 1) : []
  unroutedAgents.set(e.agentId, { ...(u ?? { task: '', why: 'subagente', same: false }), effort: stepEffort })
}

export const register: Register = (on, options) => {
  opts = options as Options
  on('prompt.submit', async ($, e, next) => {
    const task = e.text.trim()
    unroutedPending = undefined
    if (ROUTED_ORIGINS.has(e.origin.kind) && /^\/model\b/.test(task)) {
      pinned = true
      sessionModel = undefined
      return next(e)
    }
    if (pinned || !ROUTED_ORIGINS.has(e.origin.kind) || !task || task.startsWith('/')) {
      const why = pinned ? 'modelo fixado' : !ROUTED_ORIGINS.has(e.origin.kind) ? (ORIGIN_WHY[e.origin.kind] ?? e.origin.kind) : 'comando'
      if (task) unroutedPending = { task, why, same: pinned || !sessionModel }
      return next(e)
    }

    $.ui.status('JEV: a decidir…')
    let session: string | undefined
    try {
      session = await $.session.id()
    } catch {
      session = undefined // sem id, o núcleo decide cada prompt por si (como na v1)
    }
    const reset = resetPending
    resetPending = false
    const started = Date.now()
    let ran
    try {
      ran = await jev($, ['route', '--json'], {
        stdin: JSON.stringify({ task, history: history(), session, reset }),
        timeoutMs: 120_000,
      })
    } catch {
      sessionModel = undefined // o núcleo não arrancou: o prompt segue como sem o JEV
      unroutedPending = { task, why: 'núcleo em falta', same: true }
      $.ui.status(`JEV: o núcleo não arrancou; instala-o com ${INSTALL}`)
      return next(e)
    }
    const routeMs = Date.now() - started
    const route = readJson<Route>(ran.stdout)
    if (!route) {
      unroutedPending = { task, why: 'Jev sem resposta', same: true }
      sessionModel = undefined // a regra: qualquer falha cai no standard, também na v2
      $.ui.status('JEV: sem decisão, segue o standard')
      return next(e)
    }
    const d = route.decision
    if (route.free?.ok) {
      // O Jev mandou para um free: este prompt não gasta quota Anthropic. O modelo da sessão fica
      // a saber o que se passou, para os turnos seguintes.
      $.ui.status(`JEV: ${route.free.model_id.split('/').pop()} (free)${totals(route.summary)}`)
      lastExchange = { prompt: task, answer: route.free.text }
      try {
        await $.session.append({
          message: {
            type: 'user',
            content: [{ type: 'text', text: `[JEV] Pedido respondido pelo modelo free ${route.free.model_id}.\nPedido: ${task}\nResposta: ${route.free.text}` }],
          },
        })
      } catch {
        // dar contexto ao modelo da sessão é um extra; mostrar a resposta é o essencial
      }
      return { drop: `${route.free.text}\n\n— JEV: respondido por ${route.free.model_id} (free) · ${d.rationale}` }
    }
    sessionModel = (route.policy === 'v2' || route.policy === 'v3' || route.policy === 'v4') && !d.is_standard
      && route.model_id ? { model: route.model_id, effort: d.effort } : undefined
    // o route inteiro contém a decisão e o free; o máximo protege uma medição de relógio que falhe
    const waitMs = Math.max(routeMs, route.decide_ms + (route.free?.duration_ms ?? 0))
    pending = { task, route, waitMs, routeMs, scope: 'main' }
    $.ui.status(`JEV: ${label(d)}`)
    return next(e)
  })

  on('turn.start', async ($, e, next) => {
    prompts.set(e.turnId, e.text || lastExchange?.prompt || '') // uma continuação não traz texto: fica o pedido de antes
    if (pending) {
      turns.set(e.turnId, pending)
      pending = undefined
    } else {
      unrouted.set(e.turnId, unroutedPending ?? { task: e.text || lastExchange?.prompt || '', why: 'continuação', same: !sessionModel })
    }
    unroutedPending = undefined
    return next(e)
  })

  // Cada pedido do turno sai com o modelo e o esforço que o Jev escolheu (pela subscrição)
  on('turn.step', async function* ($, e, next) {
    const routed = e.agentId ? claimAgent(e) : turns.get(e.turnId)
    if (!routed) noteUnrouted(e, !e.agentId && sessionModel ? sessionModel.effort : undefined)
    if (!routed && !e.agentId && sessionModel) {
      const effort = sessionModel.effort ? { effort: sessionModel.effort } : {}
      return yield* next({ ...e, model: sessionModel.model, ...effort })
    }
    const d = routed?.route.decision
    if (!routed || !d || d.is_standard || !routed.route.model_id) return yield* next(e)
    const effort = d.effort ? { effort: d.effort } : {}
    const model = e.agentId ? {} : { model: routed.route.model_id } // o do subagente já vem do tool.call
    return yield* next({ ...e, ...model, ...effort })
  })

  on('turn.complete', async ($, e, next) => {
    if (!e.agentId) {
      lastExchange = { prompt: prompts.get(e.turnId) ?? '', answer: e.answer }
      prompts.delete(e.turnId)
    }
    const routed = e.agentId ? agents.get(e.agentId) : turns.get(e.turnId)
    if (routed) {
      if (e.agentId) agents.delete(e.agentId)
      else turns.delete(e.turnId)
      const usage: TurnUsage | null = e.usage ?? null
      // O que o núcleo guarda da sessão: a resposta (o histórico do próximo prompt) e o contexto C
      // A sessão (também num subagente: o registo por sessão junta-os) e, no turno principal, o contexto C
      let session: string | undefined
      let context: number | undefined
      try {
        session = await $.session.id()
        if (!e.agentId) context = (await $.session.usage()).context.tokens
      } catch {
        // sem isto o núcleo decide como antes; não é razão para falhar o turno
      }
      const ran = await jev($, ['record'], {
        stdin: JSON.stringify({
          task: routed.task, decision: routed.route.decision, model_id: routed.route.model_id, usage,
          duration_ms: e.durationMs + routed.waitMs, reason: e.reason, scope: routed.scope,
          session, answer: e.agentId ? undefined : e.answer.slice(-2000), context,
          route_ms: routed.routeMs, decide_ms: routed.route.decide_ms,
        }),
        timeoutMs: 60_000,
      }).catch(() => undefined) // registar é um extra: um núcleo que falhe aqui não estraga o turno
      if (!e.agentId) {
        const out = readJson<{ summary: Summary }>(ran?.stdout ?? '')
        const secs = ((e.durationMs + routed.waitMs) / 1000).toFixed(1)
        $.ui.status(`JEV: ${label(routed.route.decision)} · ${secs} s${totals(out?.summary)}`)
      }
    } else {
      const u = (e.agentId ? unroutedAgents.get(e.agentId) : unrouted.get(e.turnId))
        ?? { task: '', why: e.agentId ? 'subagente' : 'continuação', same: false }
      if (e.agentId) unroutedAgents.delete(e.agentId)
      else unrouted.delete(e.turnId)
      if (e.usage) {
        let session: string | undefined
        let context: number | undefined
        try {
          session = await $.session.id()
          if (!e.agentId) context = (await $.session.usage()).context.tokens
        } catch {
          // sem isto o registo fica sem sessão; não é razão para falhar o turno
        }
        const decision = {
          runner: 'anthropic', model: alias(e.usage.model), effort: u.effort ?? null, rationale: `sem decisão do Jev: ${u.why}`,
          is_standard: false, router_model: 'sem decisão', router_cost_usd: 0, router_error: null,
          signals: { jev: 'sem decisão', rule: u.why },
        }
        await jev($, ['record'], {
          stdin: JSON.stringify({
            task: u.task, decision, model_id: e.usage.model, usage: e.usage, duration_ms: e.durationMs, reason: e.reason,
            scope: e.agentId ? 'agent' : 'main', session, answer: e.agentId ? undefined : e.answer.slice(-2000), context,
            ...(u.same ? { baseline: 'same' } : {}),
          }),
          timeoutMs: 60_000,
        }).catch(() => undefined)
      }
    }
    return next(e)
  })

  on('session.compact', async ($, e, next) => {
    const out = await next(e)
    // `precompute` só prepara (a conversa não muda), e a de um subagente não toca na cache do turno principal
    if (e.trigger !== 'precompute' && e.agentId === undefined && !('skip' in out)) resetPending = true
    return out
  })

  // Subagentes: o Jev escolhe o modelo a partir da tarefa do agente (um subagente nunca vai para um free)
  on('tool.call', { tool: 'Agent' }, async ($, e, next) => {
    if (e.subagent_type === 'fork') { // um fork herda sempre o modelo
      queuedUnrouted.push({ task: e.prompt, why: 'fork', same: !sessionModel })
      return next(e)
    }
    const declared = e.model as Model | undefined
    // Sem decisão do Jev, a regra é o standard: nunca herdar o modelo da faixa, que pode ser baixo
    const standard = (): Model => (declared && RANK[declared] > RANK.opus ? declared : 'opus')
    const started = Date.now()
    let ran
    try {
      ran = await jev($, ['route', '--agent'], { stdin: e.prompt, timeoutMs: 60_000 })
    } catch {
      queuedUnrouted.push({ task: e.prompt, why: 'núcleo em falta', same: true, model: standard() })
      return next({ ...e, model: standard() })
    }
    const routeMs = Date.now() - started
    const route = readJson<Route>(ran.stdout)
    const d = route?.decision
    if (!route || !d || d.is_standard || d.runner !== 'anthropic') {
      queuedUnrouted.push({ task: e.prompt, why: 'Jev sem resposta', same: true, model: standard() })
      return next({ ...e, model: standard() })
    }
    // Um modelo declarado mais barato do que o do Jev não vale: a tarefa pode precisar do que o Jev escolheu
    if (declared && declared in RANK && RANK[declared] >= (RANK[d.model as Model] ?? 0)) { // o declarado já chega
      queuedUnrouted.push({ task: e.prompt, why: 'modelo declarado', same: true, model: declared })
      return next(e)
    }
    queuedAgents.push({ task: e.prompt, route, waitMs: Math.max(routeMs, route.decide_ms), routeMs, scope: 'agent' })
    return next({ ...e, model: d.model as Model })
  })
}
