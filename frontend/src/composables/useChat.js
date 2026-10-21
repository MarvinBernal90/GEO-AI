/**
 * ==============================================================================
 * UNIFIED CHAT STATE
 * ==============================================================================
 * File: frontend/src/composables/useChat.js
 *
 * One chat for everything. The backend decides what to do with each message:
 *   - a message with an address  -> viability report (data + verdict),
 *   - a message with no place    -> assistant answer ("modo" event first),
 *   - not enough information     -> a question back ("aclaracion" event).
 *
 * This composable keeps the chat bubbles and forwards the events that belong
 * to the report (location, data, verdict) to the handlers given by App.vue.
 *
 * Handlers (all optional):
 *   getThreadId()     returns the active thread id ('' when there is no user)
 *   onStart()         a message is about to be sent
 *   onAclaracion(e)   onUbicacion(e)   onDatos(e)   onToken(text)
 *   onDone(e)         onError(detail)  onCancel()
 */

import { ref } from 'vue'

import { chatInformeStream } from '../services/api.js'
import { createLogger } from '../services/logger.js'

const log = createLogger('app.chat')

const MAX_TRACE_EVENTS = 500
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

export function useChat(handlers = {}) {
  const messages = ref([])
  const sending = ref(false)
  const traceEvents = ref([]) // live pipeline steps of the last message
  const lastMetrics = ref(null) // final summary of the last message
  let controller = null

  /** Adds a message and returns the reactive copy (so it can be edited later). */
  function addMessage(role, text, kind = 'texto') {
    messages.value.push({ id: nextMessageId++, role, text, kind })
    return messages.value[messages.value.length - 1]
  }

  /** Sends the user's text and handles the stream until it ends. */
  async function send(raw) {
    const text = String(raw ?? '').trim()
    if (!text || sending.value) return

    sending.value = true
    traceEvents.value = []
    lastMetrics.value = null
    controller = new AbortController()
    handlers.onStart?.()
    addMessage('user', text)

    let modo = 'informe'
    let reply = null // the assistant bubble that receives the streamed tokens
    const threadId = handlers.getThreadId?.() || ''
    const start = performance.now()

    try {
      await chatInformeStream(
        text,
        {
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
          onUbicacion: (evento) => handlers.onUbicacion?.(evento),
          onDatos: (evento) => handlers.onDatos?.(evento),
          onToken: (chunk) => {
            if (!chunk) return
            if (modo === 'asistente' && reply) reply.text += chunk
            else handlers.onToken?.(chunk)
          },
          onDone: (evento) => {
            if (modo === 'asistente') {
              if (reply && !reply.text && evento.text) reply.text = evento.text
            } else {
              handlers.onDone?.(evento)
              if (evento.resumen) addMessage('assistant', evento.resumen)
            }
          },
          onError: (detail) => {
            if (reply && !reply.text) {
              reply.kind = 'error'
              reply.text = detail
            } else {
              addMessage('assistant', detail, 'error')
            }
            handlers.onError?.(detail)
          },
          onTrace: (evento) => {
            if (traceEvents.value.length < MAX_TRACE_EVENTS) traceEvents.value.push(evento)
          },
          onMetrics: (evento) => {
            lastMetrics.value = evento
          },
        },
        { threadId, signal: controller.signal },
      )

      if (controller.signal.aborted) {
        addMessage('assistant', 'Respuesta detenida.', 'aviso')
        handlers.onCancel?.()
      }
      // PRIVACY: only the mode and the timing are logged, never the text.
      log.event('chat.enviado', {
        modo,
        has_thread: Boolean(threadId),
        duration_ms: performance.now() - start,
      })
    } finally {
      sending.value = false
      controller = null
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

  return { messages, sending, traceEvents, lastMetrics, send, cancel, clear, loadHistory }
}
