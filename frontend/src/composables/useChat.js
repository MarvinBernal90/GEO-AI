/**
 * ==============================================================================
 * UNIFIED CHAT STATE
 * ==============================================================================
 * File: frontend/src/composables/useChat.js
 *
 * One chat for everything. The backend decides what to do with each typed
 * message:
 *   - a message with an address  -> viability report,
 *   - a message with no place    -> assistant answer ("modo" event first),
 *   - not enough information     -> a question back ("aclaracion" event).
 * The guided search (district + zone) also lands in the same conversation.
 *
 * Every report is a message of kind 'informe' that owns its data, so older
 * reports stay in the chat and the map can follow the last one.
 *
 * Message shapes:
 *   { id, role, kind: 'texto' | 'aviso' | 'error', text }
 *   { id, role: 'assistant', kind: 'informe', text: '', report }
 *
 * Report status: 'cargando' -> 'generando' -> 'listo' | 'error' | 'detenido'.
 *
 * Handlers (all optional):
 *   getThreadId()    returns the active thread id ('' when there is no user)
 *   onStart()        a request is about to be sent
 *   onAclaracion(e)  the backend needs a clarification (to pre-fill the form)
 */

import { computed, ref } from 'vue'

import { chatInformeStream, generarInformeStream } from '../services/api.js'
import { createLogger } from '../services/logger.js'

const log = createLogger('app.chat')

const MAX_TRACE_EVENTS = 500
const SEMAFOROS_VALIDOS = ['verde', 'ambar', 'rojo']
const MENSAJE_CONEXION = 'No se pudo conectar con el servidor. Inténtalo de nuevo.'
let nextMessageId = 1

/**
 * Turns the saved history text into chat messages.
 * Format written by the backend: "USUARIO:\n<text>\n\nASISTENTE:\n<text>\n\n".
 * If the text has no markers (older format), it is shown as one assistant message.
 *
 * @param {string} content
 * @returns {Array<{ id: number, role: 'user' | 'assistant', text: string, kind: string }>}
 */
export function parseHistory(content) {
  const text = String(content ?? '')
  const markers = [...text.matchAll(/^(USUARIO|ASISTENTE):\n/gm)]

  if (markers.length === 0) {
    return text.trim() ? [{ id: nextMessageId++, role: 'assistant', text: text.trim(), kind: 'texto' }] : []
  }

  return markers
    .map((marker, i) => {
      const start = marker.index + marker[0].length
      const end = i + 1 < markers.length ? markers[i + 1].index : text.length
      return {
        id: nextMessageId++,
        role: marker[1] === 'USUARIO' ? 'user' : 'assistant',
        text: text.slice(start, end).trim(),
        kind: 'texto',
      }
    })
    .filter((message) => message.text)
}

// ---------------------------------------------------------------------------
// OPTIMISTIC UI RENDERING (STREAMING TOLERANCE)
// ---------------------------------------------------------------------------
// The backend parses the LLM output robustly at the end. To give instant
// feedback while streaming, the first streamed line is used as a guess of the
// traffic light. The confirmed value from the "done" event overrides it.

/** Traffic light known so far: the confirmed one, or a guess from the stream. */
export function semaforoDe(report) {
  if (report.semaforo) return report.semaforo
  const primeraLinea = String(report.texto ?? '')
    .split('\n')[0]
    ?.trim()
    .toLowerCase()
    .replace(/[.!:;,]+$/, '') // the LLM sometimes adds punctuation (e.g. "ambar.")
  return SEMAFOROS_VALIDOS.includes(primeraLinea) ? primeraLinea : null
}

/** Summary known so far: the confirmed one, or the streamed text after the first line. */
export function resumenDe(report) {
  if (report.resumen !== null && report.resumen !== undefined) return report.resumen
  if (!semaforoDe(report)) return ''
  return String(report.texto ?? '')
    .split('\n')
    .slice(1)
    .join('\n')
    .trim()
}

function newReport({ codiDistricte = null, zonaPgm = null, ubicacion = null } = {}) {
  return {
    status: 'cargando',
    codiDistricte,
    zonaPgm,
    ubicacion, // { lat, lon } | null
    datos: null,
    respuestaLegal: '',
    articulos: [],
    texto: '',
    semaforo: null,
    resumen: null,
    error: '',
  }
}

function applyDatos(report, evento) {
  report.datos = evento.datos_distrito ?? null
  report.respuestaLegal = evento.respuesta_legal ?? ''
  report.articulos = evento.articulos_citados ?? []
  report.status = 'generando'
}

function applyDone(report, evento) {
  report.semaforo = evento.semaforo ?? null
  report.resumen = evento.resumen ?? null
  report.status = 'listo'
}

function applyError(report, detail) {
  report.status = 'error'
  report.error = detail
}

export function useChat(handlers = {}) {
  const messages = ref([])
  const sending = ref(false)
  const traceEvents = ref([]) // live pipeline steps of the last request
  const lastMetrics = ref(null) // final summary of the last request
  let controller = null

  /** The report of the most recent 'informe' message (the map follows it). */
  const lastReport = computed(() => {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      if (messages.value[i].kind === 'informe') return messages.value[i].report
    }
    return null
  })

  /** Adds a text message and returns the reactive copy (so it can be edited later). */
  function addMessage(role, text, kind = 'texto') {
    messages.value.push({ id: nextMessageId++, role, text, kind })
    return messages.value[messages.value.length - 1]
  }

  /** Adds a report message and returns its reactive report object. */
  function addReport(fields) {
    messages.value.push({
      id: nextMessageId++,
      role: 'assistant',
      kind: 'informe',
      text: '',
      report: newReport(fields),
    })
    return messages.value[messages.value.length - 1].report
  }

  function begin() {
    sending.value = true
    traceEvents.value = []
    lastMetrics.value = null
    controller = new AbortController()
    handlers.onStart?.()
  }

  function end() {
    sending.value = false
    controller = null
  }

  /** Callbacks shared by both flows: they only store the pipeline events. */
  function traceCallbacks() {
    return {
      onTrace: (evento) => {
        if (traceEvents.value.length < MAX_TRACE_EVENTS) traceEvents.value.push(evento)
      },
      onMetrics: (evento) => {
        lastMetrics.value = evento
      },
    }
  }

  /** Sends the typed text and handles the stream until it ends. */
  async function send(raw) {
    const text = String(raw ?? '').trim()
    if (!text || sending.value) return

    begin()
    addMessage('user', text)

    let modo = 'informe'
    let reply = null // the assistant bubble that receives the streamed tokens
    let report = null // the report message of this request, once it starts
    const signal = controller.signal
    const threadId = handlers.getThreadId?.() || ''
    const start = performance.now()

    try {
      await chatInformeStream(
        text,
        {
          ...traceCallbacks(),
          onModo: (evento) => {
            if (evento.modo === 'asistente') {
              modo = 'asistente'
              reply = addMessage('assistant', '')
            }
          },
          onAclaracion: (evento) => {
            addMessage('assistant', evento.mensaje, 'aviso')
            handlers.onAclaracion?.(evento)
          },
          onUbicacion: (evento) => {
            report = addReport({
              codiDistricte: evento.codi_districte,
              zonaPgm: evento.zona_pgm,
              ubicacion: { lat: evento.lat, lon: evento.lon },
            })
          },
          onDatos: (evento) => {
            if (!report) report = addReport()
            applyDatos(report, evento)
          },
          onToken: (chunk) => {
            if (!chunk) return
            if (modo === 'asistente' && reply) reply.text += chunk
            else if (report) report.texto += chunk
          },
          onDone: (evento) => {
            if (modo === 'asistente') {
              if (reply && !reply.text && evento.text) reply.text = evento.text
            } else {
              if (!report) report = addReport()
              applyDone(report, evento)
            }
          },
          onError: (detail) => {
            if (report && report.status !== 'listo') applyError(report, detail)
            else if (reply && !reply.text) {
              reply.kind = 'error'
              reply.text = detail
            } else addMessage('assistant', detail, 'error')
          },
        },
        { threadId, signal },
      )

      if (signal.aborted) {
        if (report && report.status !== 'listo') report.status = 'detenido'
        else addMessage('assistant', 'Respuesta detenida.', 'aviso')
      }
      // PRIVACY: only the mode and the timing are logged, never the text.
      log.event('chat.enviado', {
        modo,
        informe: Boolean(report),
        semaforo: report?.semaforo ?? null,
        has_thread: Boolean(threadId),
        duration_ms: performance.now() - start,
      })
    } catch (err) {
      log.error('Chat stream failed', { error: err })
      if (report && report.status !== 'listo') applyError(report, MENSAJE_CONEXION)
      else addMessage('assistant', MENSAJE_CONEXION, 'error')
    } finally {
      end()
    }
  }

  /**
   * Generates a report from the guided search (district + zone).
   * @param {{ codiDistricte: number, zonaPgm: string, ubicacion: {lat: number, lon: number} | null,
   *           distritoNombre?: string, zonaNombre?: string }} params
   */
  async function sendGuided(params) {
    if (sending.value) return
    const { codiDistricte, zonaPgm, ubicacion = null, distritoNombre = '', zonaNombre = '' } = params

    begin()
    const distrito = distritoNombre || `distrito ${codiDistricte}`
    addMessage('user', `Informe de ${distrito}${zonaNombre ? ` · ${zonaNombre}` : ''}`)
    const report = addReport({ codiDistricte, zonaPgm, ubicacion })
    const signal = controller.signal
    const start = performance.now()

    try {
      await generarInformeStream(
        codiDistricte,
        zonaPgm,
        {
          ...traceCallbacks(),
          onDatos: (evento) => applyDatos(report, evento),
          onToken: (chunk) => {
            if (chunk) report.texto += chunk
          },
          onDone: (evento) => applyDone(report, evento),
          onError: (detail) => applyError(report, detail),
        },
        { signal },
      )

      if (signal.aborted && report.status !== 'listo') report.status = 'detenido'
      log.event('informe.completado', {
        codi_districte: codiDistricte,
        zona_pgm: zonaPgm,
        semaforo: report.semaforo,
        duration_ms: performance.now() - start,
        articulos_citados: report.articulos.length,
      })
    } catch (err) {
      log.error('Report stream failed', { error: err })
      applyError(report, MENSAJE_CONEXION)
    } finally {
      end()
    }
  }

  /** Stops the answer that is being generated. */
  function cancel() {
    controller?.abort()
  }

  /** Empties the conversation (does not touch the saved history). */
  function clear() {
    messages.value = []
  }

  /** Replaces the conversation with a saved history. */
  function loadHistory(content) {
    messages.value = parseHistory(content)
  }

  return {
    messages,
    sending,
    lastReport,
    traceEvents,
    lastMetrics,
    send,
    sendGuided,
    cancel,
    clear,
    loadHistory,
  }
}
