import { createLogger, generateTraceId } from './logger'

/**
 * ==============================================================================
 * API GATEWAY & NETWORK SERVICE LAYER
 * ==============================================================================
 * File: frontend/src/services/api.js
 *
 * Abstracts all HTTP communication with the FastAPI Backend.
 * Implements centralized error handling and manual Server-Sent Events (SSE)
 * parsing for AI LLM Streaming.
 */

/**
 * Base API URL derived from Vite's environment variables.
 * @constant {string}
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

const log = createLogger('api')

/**
 * Centralized Error Handler.
 * Intercepts failed HTTP responses, attempts to parse FastAPI's specific
 * `detail` field, and throws a normalized JavaScript Error for the UI to catch.
 */
async function handleResponse(response) {
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    let mensaje = `Error HTTP ${response.status}: Error al conectar con el servidor.`
    if (typeof body?.detail === 'string') {
      mensaje = body.detail
    } else if (Array.isArray(body?.detail) && body.detail[0]?.msg) {
      mensaje = body.detail[0].msg
    }
    const error = new Error(mensaje)
    error.status = response.status
    throw error
  }
  return response.json()
}

/**
 * fetch wrapper that adds correlation, timing and error logging.
 *
 * The trace id travels in `X-Request-ID` and the backend propagates it to
 * every log line of that request, so a failed call can be followed through
 * to the RAG, agent and database lines it produced.
 *
 * @param {string} operation
 * @param {string} url
 * @param {RequestInit} [options]
 * @returns {Promise<any>}
 */
async function request(operation, url, options = {}) {
  const traceId = generateTraceId()
  const start = performance.now()

  try {
    const response = await fetch(url, {
      ...options,
      headers: { ...(options.headers || {}), 'X-Request-ID': traceId },
    })
    const data = await handleResponse(response)

    log.debug(`${operation} ok`, {
      trace_id: traceId,
      duration_ms: performance.now() - start,
      operation,
      status: response.status,
    })
    return data
  } catch (error) {
    log.error(`${operation} failed`, {
      error,
      trace_id: traceId,
      duration_ms: performance.now() - start,
      operation,
      status: error.status,
    })
    throw error
  }
}

/** Fetches available districts. */
export async function obtenerDistritos() {
  return request('obtenerDistritos', `${API_BASE_URL}/api/districts`)
}

/** Fetches urban zoning classifications (Claus PGM). */
export async function obtenerZonasPgm() {
  return request('obtenerZonasPgm', `${API_BASE_URL}/api/pgm-zones`)
}

/** Retrieves the full text of a specific legal article for verification. */
export async function obtenerArticulo(fuenteLegal, numeroArticulo) {
  const params = new URLSearchParams({ fuente_legal: fuenteLegal, numero_articulo: numeroArticulo })
  return request('obtenerArticulo', `${API_BASE_URL}/api/articles?${params}`)
}

/**
 * Geocodes a free-text address -- returns the suggested district and PGM
 * zone, when they can be determined. Throws an error (which handleResponse
 * turns into an Error carrying the backend's detail) if the address is not
 * found within Barcelona.
 *
 * PRIVACY: the address typed by the user is personal data and is never
 * logged -- only the outcome (whether it matched, and which district/zone).
 */
export async function geocodificarDireccion(direccion) {
  const params = new URLSearchParams({ direccion })
  return request('geocodificarDireccion', `${API_BASE_URL}/api/geocode?${params}`)
}

/**
 * Fetches commercial competitors. If coordinates {lat, lon} are provided,
 * performs a geospatial radius search instead of a district-wide search.
 */
export async function obtenerCompetidores(codiDistricte, ubicacion = null) {
  const params = new URLSearchParams({ codi_districte: codiDistricte })
  if (ubicacion) {
    params.set('lat', ubicacion.lat)
    params.set('lon', ubicacion.lon)
  }
  return request('obtenerCompetidores', `${API_BASE_URL}/api/competitors?${params}`)
}

/**
 * ==============================================================================
 * SERVER-SENT EVENTS (SSE) OVER POST
 * ==============================================================================
 * Browsers' native EventSource API only supports GET requests. Because we must
 * send a JSON payload (POST), we read the network byte stream by hand with the
 * Fetch API's Response Reader.
 *
 * All three streams (report, chat, assistant) share the same reader. Every
 * stream may call any of these callbacks; an event the endpoint never sends
 * simply never fires its callback.
 *
 *   onAclaracion(event)  the chat needs more input (district only, no address)
 *   onUbicacion(event)   the address was found, so the map can center on it
 *   onModo(event)        the chat switched mode (e.g. { modo: 'asistente' })
 *   onDatos(event)       district data and legal answer are ready
 *   onToken(text)        one piece of the streamed answer
 *   onDone(event)        the answer is complete
 *   onError(detail)      something failed (backend event or network error)
 *   onTrace(event)       one pipeline step started or ended ({ phase, span })
 *   onMetrics(event)     final request summary (tokens, cost, latency)
 */

/**
 * Builds the table that maps an SSE event type to its callback.
 * Unknown event types are not in the table, so they are ignored.
 */
function buildHandlers(callbacks) {
  const { onAclaracion, onUbicacion, onModo, onDatos, onToken, onDone, onError, onTrace, onMetrics } = callbacks
  return {
    aclaracion: (evento) => onAclaracion?.(evento),
    ubicacion: (evento) => onUbicacion?.(evento),
    modo: (evento) => onModo?.(evento),
    datos: (evento) => onDatos?.(evento),
    token: (evento) => onToken?.(evento.text),
    done: (evento) => onDone?.(evento),
    error: (evento) => onError?.(evento.detail),
    trace: (evento) => onTrace?.(evento),
    metrics_summary: (evento) => onMetrics?.(evento),
  }
}

/**
 * Parses one raw SSE block ("data: {...}") into an event object.
 * Returns null if the block is not a data block or the JSON is broken.
 */
function parseBlock(bloque, streamLog, counters) {
  if (!bloque.startsWith('data: ')) return null
  try {
    return JSON.parse(bloque.slice(6))
  } catch (error) {
    counters.corruptBlocks += 1
    streamLog.warn('Malformed SSE block, ignored', {
      error,
      fragment: String(bloque).slice(0, 200),
    })
    return null
  }
}

/**
 * Calls the callback of one event. A bug inside a callback is logged but it
 * must not stop the stream, and it is not a "malformed block".
 */
function dispatch(evento, handlers, streamLog) {
  if (!Object.hasOwn(handlers, evento?.type)) return
  if (evento.type === 'error') {
    streamLog.error('Backend reported an error during streaming', { detail: evento.detail })
  }
  try {
    handlers[evento.type](evento)
  } catch (error) {
    streamLog.error('Stream callback failed', { error, event_type: evento.type })
  }
}

/**
 * Opens a POST stream and sends every event to the matching callback.
 *
 * PRIVACY: the body (user text, thread id) is never logged.
 *
 * @param {object} config
 * @param {string} config.operation   Short name used in logs
 * @param {string} config.path        API path, e.g. '/api/assistant'
 * @param {object} config.body        JSON body
 * @param {object} config.callbacks   See the callback list above
 * @param {string} config.doneEvent   Name of the log event written at the end
 * @param {string} config.httpError   Message used when the HTTP status is not ok
 * @param {object} [config.logContext] Extra safe fields for every log line
 * @param {AbortSignal} [config.signal] Lets the caller cancel the stream
 * @returns {Promise<string>} The trace id sent in X-Request-ID
 */
async function streamSSE({ operation, path, body, callbacks, doneEvent, httpError, logContext = {}, signal }) {
  const traceId = generateTraceId()
  const start = performance.now()
  const streamLog = log.child({ trace_id: traceId, operation, ...logContext })
  const handlers = buildHandlers(callbacks)
  const counters = { corruptBlocks: 0 }

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Request-ID': traceId },
      body: JSON.stringify(body),
      signal,
    })

    if (!response.ok) {
      const errorBody = await response.json().catch(() => null)
      throw new Error(errorBody?.detail || `${httpError} (${response.status})`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const bloques = buffer.split('\n\n')

      // Network Chunking Safety: keep the last fragment if it is incomplete,
      // so JSON.parse never sees half an event.
      buffer = bloques.pop() ?? ''

      for (const bloque of bloques) {
        const evento = parseBlock(bloque, streamLog, counters)
        if (evento) dispatch(evento, handlers, streamLog)
      }
    }

    streamLog.event(doneEvent, {
      duration_ms: performance.now() - start,
      corrupt_blocks: counters.corruptBlocks,
    })
  } catch (error) {
    // A cancel made by the caller is not a failure.
    if (error?.name === 'AbortError') return traceId
    streamLog.error('Streaming failed', {
      error,
      duration_ms: performance.now() - start,
    })
    callbacks.onError?.(error.message)
  }
  return traceId
}

/**
 * Streams a report for a district and a PGM zone (/api/reports/stream).
 *
 * @param {number} codiDistricte
 * @param {string} zonaPgm
 * @param {object} [callbacks]
 * @param {{ signal?: AbortSignal }} [options]
 */
export async function generarInformeStream(codiDistricte, zonaPgm, callbacks = {}, options = {}) {
  return streamSSE({
    operation: 'generarInformeStream',
    path: '/api/reports/stream',
    body: { codi_districte: codiDistricte, zona_pgm: zonaPgm },
    callbacks,
    doneEvent: 'informe.generado',
    httpError: 'Error al llamar a la API',
    logContext: { codi_districte: codiDistricte, zona_pgm: zonaPgm },
    signal: options.signal,
  })
}

/**
 * Unified chat stream (POST /api, see routers/chat.py).
 *
 * With an address the backend answers with a report. With a thread id and no
 * address it answers as the assistant and sends a 'modo' event first. Without
 * a thread id and without an address it asks for more input ('aclaracion').
 *
 * @param {string} mensaje - What the user typed
 * @param {object} [callbacks]
 * @param {{ threadId?: string, signal?: AbortSignal }} [options]
 */
export async function chatInformeStream(mensaje, callbacks = {}, options = {}) {
  // The backend rejects unknown fields, so thread_id is sent only when set.
  const body = { mensaje }
  if (options.threadId) body.thread_id = options.threadId

  return streamSSE({
    operation: 'chatInformeStream',
    path: '/api',
    body,
    callbacks,
    doneEvent: 'chat.completado',
    httpError: 'Error al llamar a la API',
    logContext: { has_thread: Boolean(options.threadId) },
    signal: options.signal,
  })
}

/**
 * Streams responses from the conversational assistant endpoint (/api/assistant).
 *
 * @param {string} prompt - Prompt or user query
 * @param {string} threadId - Conversation thread ID (e.g. username:ordinal)
 * @param {object} [callbacks]
 * @param {{ signal?: AbortSignal }} [options]
 */
export async function assistantStream(prompt, threadId, callbacks = {}, options = {}) {
  return streamSSE({
    operation: 'assistantStream',
    path: '/api/assistant',
    body: { prompt, thread_id: threadId },
    callbacks,
    doneEvent: 'asistente.completado',
    httpError: 'Error al llamar al asistente',
    signal: options.signal,
  })
}

/**
 * Authenticates a user and retrieves their conversation threads.
 *
 * @param {string} user - Username to verify
 * @returns {Promise<{ user: string, conversations: Array<{ id: string, title: string }> }>}
 */
export async function loginUser(user) {
  return request('loginUser', `${API_BASE_URL}/api/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user }),
  })
}

/**
 * Retrieves the chat conversation history for a given thread_id.
 *
 * @param {string} threadId - Conversation thread ID
 * @returns {Promise<{ thread_id: string, content: string, filename: string }>}
 */
export async function getHistory(threadId) {
  return request('getHistory', `${API_BASE_URL}/api/gethistory?thread_id=${encodeURIComponent(threadId)}`, {
    method: 'GET',
  })
}

/**
 * ==============================================================================
 * REQUEST METRICS (read-only, feeds the /metrics dashboard)
 * ==============================================================================
 * The backend saves one record per measured request. These calls only read them.
 */

/** Builds a query string, skipping empty values so the backend applies its defaults. */
function buildQuery(params) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') query.set(key, value)
  }
  return query.toString()
}

/**
 * KPIs, time series and breakdowns of a time window.
 *
 * @param {'24h'|'7d'|'30d'|'all'} [range]
 */
export async function getMetricsOverview(range = '24h') {
  return request('getMetricsOverview', `${API_BASE_URL}/api/metrics/overview?${buildQuery({ range })}`)
}

/**
 * One page of request records.
 *
 * @param {object} [filters]
 * @param {string} [filters.range]     24h | 7d | 30d | all
 * @param {string} [filters.status]    ok | error | cancelled
 * @param {string} [filters.route]
 * @param {string} [filters.model]     model name, or 'unknown'
 * @param {string} [filters.trace_id]  part of a trace id
 * @param {string} [filters.sort]      created_at | elapsed_ms | ttft_ms | tokens_out | cost_usd
 * @param {string} [filters.direction] asc | desc
 * @param {number} [filters.limit]
 * @param {number} [filters.offset]
 */
export async function getMetricsRequests(filters = {}) {
  return request('getMetricsRequests', `${API_BASE_URL}/api/metrics/requests?${buildQuery(filters)}`)
}

/** One request with all its steps (spans). */
export async function getMetricsRequest(id) {
  return request('getMetricsRequest', `${API_BASE_URL}/api/metrics/requests/${encodeURIComponent(id)}`)
}
