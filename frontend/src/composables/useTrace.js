/**
 * useTrace: turns the raw SSE trace events of the LAST request into what the
 * screen draws: steps (spans), lanes per actor, a step-by-step log and the
 * totals of the header bar.
 *
 * Pure logic, no components. It accepts two event shapes:
 *   - real:      { type: 'trace', phase, span: { id, parent_id, start_ms, duration_ms, ... } }
 *   - contract:  { type: 'trace', phase, id, parent, at, ms, ... }
 * and tolerates missing fields: with no events it returns an empty "waiting"
 * state, so an old backend never breaks the page.
 */
import { computed, onBeforeUnmount, ref, toValue, watch } from 'vue'

// Backend prices are in USD; the screen shows euros. Same default as the backend setting.
const EUR_POR_USD = Number(import.meta.env.VITE_EUR_PER_USD) || 0.86

export const ACTORES = {
  agent: { label: 'Agente', color: '#5b8cff' },
  llm: { label: 'LLM', color: '#b48cff' },
  rag: { label: 'RAG', color: '#3fb27f' },
  db: { label: 'Base de datos', color: '#e0a63a' },
  external: { label: 'Externo', color: '#ff6f7d' },
}
const OTROS = { label: 'Otros', color: '#8b93a7' }
const ORDEN = ['agent', 'llm', 'rag', 'db', 'external']

// Spanish names for the steps we know. Unknown names are shown cleaned up.
const ETIQUETAS_PASO = {
  chat_pipeline: 'Consulta completa',
  sintesis_final: 'Síntesis del veredicto',
  llm_call_stream: 'Llamada al modelo (streaming)',
}

export function etiquetaPaso(nombre) {
  if (!nombre) return 'Paso'
  if (ETIQUETAS_PASO[nombre]) return ETIQUETAS_PASO[nombre]
  const texto = String(nombre).replace(/[_-]+/g, ' ').trim()
  return texto.charAt(0).toUpperCase() + texto.slice(1)
}

// ---------------------------------------------------------------------------
// FORMATTERS (Spanish)
// ---------------------------------------------------------------------------
const formatoNumero = new Intl.NumberFormat('es-ES')
const formatoEuros = new Intl.NumberFormat('es-ES', {
  style: 'currency',
  currency: 'EUR',
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
})

export const formatearNumero = (n) => formatoNumero.format(n ?? 0)
export const formatearEuros = (n) => formatoEuros.format(n ?? 0)

export function formatearTiempo(ms) {
  if (ms == null || !Number.isFinite(ms)) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  const segundos = (ms / 1000).toLocaleString('es-ES', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
  return `${segundos} s`
}

// ---------------------------------------------------------------------------
// EVENTS -> STEPS
// ---------------------------------------------------------------------------
const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const claveActor = (actor) => (ORDEN.includes(actor) ? actor : 'otros')

/** One raw event -> one flat step with our own field names, or null. */
function normalizar(evento) {
  const s = evento?.span ?? evento
  if (!s || s.id == null) return null
  return {
    id: s.id,
    parent: s.parent_id ?? s.parent ?? null,
    actor: s.actor ?? 'otros',
    name: s.name ?? '',
    start: num(s.start_ms ?? s.at),
    ms: num(s.duration_ms ?? s.ms),
    status: s.status ?? 'ok',
    error: s.error ?? null,
    model: s.model ?? null,
    tokensIn: num(s.tokens_in),
    tokensOut: num(s.tokens_out),
    cost: num(s.cost_usd),
    cached: s.cached ?? null,
    input: s.input_summary ?? s.input ?? null,
    output: s.output_summary ?? s.output ?? null,
    ttft: num(s.ttft_ms),
  }
}

/**
 * Merges the events of ONE request by span id (start -> update -> end become a
 * single step; later non-null values win). A new root "start" means a new
 * request began, so everything before it is dropped.
 */
function construirPasos(eventos) {
  let pasos = new Map()
  for (const evento of eventos ?? []) {
    if (evento?.type && evento.type !== 'trace') continue
    const nuevo = normalizar(evento)
    if (!nuevo) continue
    const fase = evento.phase ?? 'end'
    if (fase === 'start' && nuevo.parent === null) pasos = new Map()

    const previo = pasos.get(nuevo.id) ?? {}
    const unido = { ...previo }
    for (const [clave, valor] of Object.entries(nuevo)) {
      if (valor !== null && valor !== undefined) unido[clave] = valor
    }
    unido.parent = unido.parent ?? null
    unido.hecho = Boolean(previo.hecho) || fase === 'end'
    pasos.set(nuevo.id, unido)
  }
  return [...pasos.values()]
}

/** Total time covered by a list of [from, to] intervals (overlaps counted once). */
function tiempoUnion(intervalos) {
  const orden = intervalos.filter(([a, b]) => b > a).sort((x, y) => x[0] - y[0])
  let total = 0
  let ini = null
  let fin = null
  for (const [a, b] of orden) {
    if (ini === null) {
      ini = a
      fin = b
    } else if (a <= fin) {
      fin = Math.max(fin, b)
    } else {
      total += fin - ini
      ini = a
      fin = b
    }
  }
  if (ini !== null) total += fin - ini
  return total
}

// ---------------------------------------------------------------------------
// COMPOSABLE
// ---------------------------------------------------------------------------
/**
 * @param {object} opciones
 * @param {import('vue').MaybeRefOrGetter<Array>} opciones.eventos  raw trace events
 * @param {import('vue').MaybeRefOrGetter<boolean>} opciones.enCurso  true while the answer streams
 */
export function useTrace({ eventos, enCurso }) {
  // Local clock: only ticks while a request is running (live time, running steps).
  const ahora = ref(Date.now())
  const inicioLocal = ref(null)
  let temporizador = null

  watch(
    () => Boolean(toValue(enCurso)),
    (activo) => {
      clearInterval(temporizador)
      temporizador = null
      ahora.value = Date.now()
      if (activo) {
        inicioLocal.value = ahora.value
        temporizador = setInterval(() => {
          ahora.value = Date.now()
        }, 100)
      }
    },
    { immediate: true },
  )
  onBeforeUnmount(() => clearInterval(temporizador))

  const traza = computed(() => {
    const activo = Boolean(toValue(enCurso))
    const transcurrido = activo && inicioLocal.value != null ? Math.max(0, ahora.value - inicioLocal.value) : null

    const crudos = construirPasos(toValue(eventos))
    const arranques = crudos.map((p) => p.start).filter((v) => v != null)
    const raizCruda = crudos.find((p) => p.parent === null)
    const inicio = raizCruda?.start ?? (arranques.length ? Math.min(...arranques) : null)

    // Times relative to the start of the request. A running step grows with the local clock.
    const pasos = crudos.map((p) => {
      const desde = p.start != null && inicio != null ? Math.max(0, p.start - inicio) : 0
      const enMarcha = !p.hecho && activo
      const dur = p.ms ?? (enMarcha ? Math.max(0, (transcurrido ?? 0) - desde) : 0)
      return { ...p, desde, dur, enMarcha, etiqueta: etiquetaPaso(p.name) }
    })

    const finMax = pasos.reduce((m, p) => Math.max(m, p.desde + p.dur), 0)
    const raiz = pasos.find((p) => p.parent === null) ?? null
    // The closing event of the root step can arrive after the stream ended: rebuild its length.
    if (raiz && raiz.ms == null && !raiz.enMarcha) raiz.dur = Math.max(0, finMax - raiz.desde)

    const elapsedMs = raiz ? raiz.dur : activo ? (transcurrido ?? 0) : finMax
    const eje = Math.max(elapsedMs, finMax, 1)

    // ---- Header totals
    const suma = (campo) => pasos.reduce((t, p) => t + (p[campo] ?? 0), 0)
    const tokensIn = suma('tokensIn')
    const tokensOut = suma('tokensOut')

    let ttftMs = raiz?.ttft ?? null
    if (ttftMs == null) {
      const llm = pasos.find((p) => p.actor === 'llm' && p.ttft != null)
      if (llm) ttftMs = llm.desde + llm.ttft
    }

    const conCoste = pasos.filter((p) => p.cost != null)
    const costeEur = conCoste.length ? conCoste.reduce((t, p) => t + p.cost, 0) * EUR_POR_USD : null
    const sinTarifa = !costeEur && tokensIn + tokensOut > 0

    const modelos = [...new Set(pasos.map((p) => p.model).filter(Boolean))]

    // ---- Lanes (one per actor, same time axis)
    const hayOtros = pasos.some((p) => claveActor(p.actor) === 'otros')
    const carriles = [...ORDEN, ...(hayOtros ? ['otros'] : [])].map((clave) => {
      const info = ACTORES[clave] ?? OTROS
      const delCarril = pasos
        .filter((p) => claveActor(p.actor) === clave)
        .map((p) => {
          const izq = Math.min((p.desde / eje) * 100, 99.4)
          const ancho = Math.min(Math.max((p.dur / eje) * 100, 0.6), 100 - izq)
          return { ...p, izq, ancho }
        })
      return {
        clave,
        label: info.label,
        color: info.color,
        pasos: delCarril,
        llamadas: delCarril.length,
        ocupadoMs: tiempoUnion(delCarril.map((p) => [p.desde, p.desde + p.dur])),
      }
    })

    // ---- Step-by-step log (tree in start order)
    const porId = new Map(pasos.map((p) => [p.id, p]))
    const hijos = new Map()
    for (const p of pasos) {
      const clave = p.parent != null && porId.has(p.parent) ? p.parent : null
      if (!hijos.has(clave)) hijos.set(clave, [])
      hijos.get(clave).push(p)
    }
    for (const lista of hijos.values()) lista.sort((a, b) => a.desde - b.desde || a.id - b.id)

    const filas = []
    const recorrer = (clave, profundidad) => {
      for (const p of hijos.get(clave) ?? []) {
        const info = ACTORES[claveActor(p.actor)] ?? OTROS
        filas.push({
          id: p.id,
          etiqueta: p.etiqueta,
          color: info.color,
          profundidad,
          dur: p.dur,
          modelo: p.model,
          tokensIn: p.tokensIn,
          tokensOut: p.tokensOut,
          cached: p.cached === true,
          estado: p.status === 'error' ? 'error' : p.enMarcha ? 'en_curso' : 'hecho',
          error: p.error,
          input: p.input,
          output: p.output,
          detalle: Boolean(p.input || p.output || p.error),
        })
        recorrer(p.id, profundidad + 1)
      }
    }
    recorrer(null, 0)

    let estado = 'espera'
    if (activo || pasos.some((p) => p.enMarcha)) estado = 'procesando'
    else if (pasos.length) estado = raiz?.status === 'error' ? 'error' : 'completado'

    return {
      hayDatos: pasos.length > 0,
      estado,
      pasos,
      carriles,
      filas,
      duracionEjeMs: eje,
      totales: { tokensIn, tokensOut, elapsedMs, ttftMs, costeEur, sinTarifa, modelos },
    }
  })

  return { traza }
}
