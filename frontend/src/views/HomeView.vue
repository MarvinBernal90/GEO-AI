<!--
==============================================================================
ROOT COMPONENT & STATE ORCHESTRATOR
==============================================================================
File: frontend/src/views/HomeView.vue

This is the main page (route "/"). It manages the global application state
(coordinates, active district, streaming status) and distributes it down to
its child components (Map, Verdict, Chat) via props.
Layout:
- Top Header: Geo-Yield-AI brand tag on the left and Métricas button at the right end.
- Interactive Chat Panel: Full-width prompt text box, actions, and real-time response.
- Results Section: Full-width dossier verdict, district map, and legal basis.
-->
<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import VerdictCard from '../components/VerdictCard.vue'
import ChatBubble from '../components/ChatBubble.vue'
import DistrictMap from '../components/DistrictMap.vue'
import RegulationsViewer from '../components/RegulationsViewer.vue'
import { assistantStream, chatInformeStream, generarInformeStream, getHistory, loginUser } from '../services/api.js'
import { createLogger } from '../services/logger.js'

defineOptions({ name: 'HomeView' })

const log = createLogger('app.informe')

const SEMAFOROS_VALIDOS = ['verde', 'ambar', 'rojo']

// Global UI State
const cargando = ref(false)
const error = ref(null)
const articuloSeleccionado = ref(null)

// Global Data State
const codiDistrictePedido = ref(null)
const ubicacionPedida = ref(null)
const datosDistrito = ref(null)
const respuestaLegal = ref('')
const articulosCitados = ref([])
const textoSintesis = ref('')

// ---------------------------------------------------------------------------
// OPTIMISTIC UI RENDERING (STREAMING TOLERANCE)
// ---------------------------------------------------------------------------
// The backend ultimately parses the LLM output robustly. However, to provide
// instant UX feedback during streaming, the frontend aggressively guesses the
// color from the very first token. If it hallucinates (e.g., "ambar."), the
// `semaforoConfirmado` variable will override it once the stream finishes.
const semaforoConfirmado = ref(null)
const resumenConfirmado = ref(null)

const semaforo = computed(() => {
  if (semaforoConfirmado.value) return semaforoConfirmado.value
  const primeraLinea = textoSintesis.value
    .split('\n')[0]
    ?.trim()
    .toLowerCase()
    .replace(/[.!:;,]+$/, '') // el LLM a veces añade puntuación al final (p. ej. "ambar.")
  return SEMAFOROS_VALIDOS.includes(primeraLinea) ? primeraLinea : null
})

const resumen = computed(() => {
  if (resumenConfirmado.value !== null) return resumenConfirmado.value
  if (!semaforo.value) return ''
  return textoSintesis.value.split('\n').slice(1).join('\n').trim()
})

const tieneResultados = computed(() => datosDistrito.value || respuestaLegal.value)

function reiniciarResultados() {
  error.value = null
  datosDistrito.value = null
  respuestaLegal.value = ''
  articulosCitados.value = []
  textoSintesis.value = ''
  semaforoConfirmado.value = null
  resumenConfirmado.value = null
}

async function onGenerar({ codiDistricte, zonaPgm, ubicacion }) {
  const inicio = performance.now()
  cargando.value = true
  codiDistrictePedido.value = codiDistricte
  ubicacionPedida.value = ubicacion
  reiniciarResultados()

  await generarInformeStream(codiDistricte, zonaPgm, {
    onDatos: (evento) => {
      datosDistrito.value = evento.datos_distrito
      respuestaLegal.value = evento.respuesta_legal
      articulosCitados.value = evento.articulos_citados
      cargando.value = false
    },
    onToken: (texto) => {
      textoSintesis.value += texto
    },
    onError: (detail) => {
      error.value = detail
      cargando.value = false
    },
    onDone: (evento) => {
      semaforoConfirmado.value = evento.semaforo
      resumenConfirmado.value = evento.resumen
      cargando.value = false

      log.event('informe.completado', {
        codi_districte: codiDistricte,
        zona_pgm: zonaPgm,
        semaforo: evento.semaforo,
        duration_ms: performance.now() - inicio,
        articulos_citados: articulosCitados.value.length,
      })
    },
  })
}

// ---------------------------------------------------------------------------
// PROMPT & RESPONSE PANEL STATE
// ---------------------------------------------------------------------------
const mensajeChat = ref('')
const respuestaPrompt = ref('')
const procesandoChat = ref(false)
const copiadoExitoso = ref(false)
const responseTextarea = ref(null)
const chatScrollContainer = ref(null)

const listaMensajesChat = computed(() => {
  if (!respuestaPrompt.value || !respuestaPrompt.value.trim()) return []
  const raw = respuestaPrompt.value.trim()
  const blocks = raw.split(/(?:^|\n)(?=PROMPT:\s*)/)
  const list = []
  for (const b of blocks) {
    const trimmed = b.trim()
    if (!trimmed) continue
    if (trimmed.startsWith('PROMPT:')) {
      const parts = trimmed.split(/\nRESPONSE:\s*/)
      const promptText = parts[0].replace('PROMPT:', '').trim()
      if (promptText) {
        list.push({ role: 'user', text: promptText })
      }
      if (parts.length > 1 && parts[1].trim()) {
        list.push({ role: 'assistant', text: parts[1].trim() })
      }
    } else if (trimmed.startsWith('AVISO:')) {
      list.push({ role: 'assistant', text: trimmed })
    } else {
      list.push({ role: 'assistant', text: trimmed })
    }
  }
  return list
})
const botonInformeDeshabilitado = ref(true)
const datosInformeChat = ref(null)

const usuarioGuardado = typeof localStorage !== 'undefined' ? localStorage.getItem('geoyield_user') : null
const usuario = ref(usuarioGuardado || '')
const username = ref(usuarioGuardado || null)
if (typeof window !== 'undefined') {
  window.username = usuarioGuardado || null
}
const usuarioLogueado = username
const cargandoLogin = ref(false)

const conversacionSeleccionada = ref(localStorage.getItem('geoyield_conversation') || '')
const conversaciones = ref([])
const thread_id = ref('')

function updateThreadId() {
  const currentUsername = username.value || ''
  if (!currentUsername) {
    thread_id.value = ''
    if (typeof window !== 'undefined') {
      window.thread_id = ''
    }
    return
  }
  if (!conversacionSeleccionada.value || conversacionSeleccionada.value === 'nueva conversación') {
    const ordinal = (conversaciones.value ? conversaciones.value.length : 0) + 1
    thread_id.value = `${currentUsername}:${ordinal}`
  } else {
    const selected = conversacionSeleccionada.value
    if (!selected.includes(':')) {
      thread_id.value = `${currentUsername}:${selected}`
    } else {
      thread_id.value = selected
    }
  }
  if (typeof window !== 'undefined') {
    window.thread_id = thread_id.value
  }
}

watch(username, (val) => {
  if (typeof window !== 'undefined') {
    window.username = val
  }
})

watch([conversacionSeleccionada, conversaciones, username], () => {
  updateThreadId()
})

updateThreadId()

async function onLogin() {
  const u = usuario.value.trim()
  if (!u) {
    username.value = null
    if (typeof window !== 'undefined') {
      window.username = null
    }
    updateThreadId()
    return
  }
  if (cargandoLogin.value) return

  cargandoLogin.value = true
  try {
    const data = await loginUser(u)
    username.value = data.user
    if (typeof window !== 'undefined') {
      window.username = data.user
    }
    localStorage.setItem('geoyield_user', data.user)
    conversaciones.value = data.conversations || []
    conversacionSeleccionada.value = ''
    updateThreadId()
    log.event('user.login.success', { user: data.user, conversations_count: conversaciones.value.length })
  } catch (err) {
    // if the response code is not a 200, show the error message in user-input text box substituing its contents
    usuario.value = err.message || 'Error al iniciar sesión'
    username.value = null
    if (typeof window !== 'undefined') {
      window.username = null
    }
    localStorage.removeItem('geoyield_user')
    conversaciones.value = []
    conversacionSeleccionada.value = ''
    updateThreadId()
    log.event('user.login.error', { user: u, error: err.message })
  } finally {
    cargandoLogin.value = false
  }
}

async function onSeleccionarConversacion() {
  mensajeChat.value = ''
  respuestaPrompt.value = ''
  updateThreadId()

  const selected = conversacionSeleccionada.value
  const isNueva = !selected || selected === 'nueva conversación'

  if (isNueva) {
    localStorage.removeItem('geoyield_conversation')
    log.event('conversation.selected', {
      conversation_id: 'nueva_conversacion',
      thread_id: thread_id.value,
      user: username.value,
    })
    return
  }

  localStorage.setItem('geoyield_conversation', selected)
  const currentThreadId = thread_id.value || selected

  log.event('conversation.selected', {
    conversation_id: selected,
    thread_id: currentThreadId,
    user: username.value,
  })

  try {
    const data = await getHistory(currentThreadId)
    if (data && typeof data.content === 'string') {
      respuestaPrompt.value = data.content
      autoScrollResponse()
    }
  } catch (err) {
    log.error('Failed to load conversation history', {
      thread_id: currentThreadId,
      error: err.message,
    })
  }
}

const distritoDesdeChat = ref(null)
const zonaDesdeChat = ref(null)
const ubicacionDesdeChat = ref(null)
const mensajeAclaracionChat = ref(null)

function limpiarPrompt() {
  mensajeChat.value = ''
}

function limpiarRespuesta() {
  respuestaPrompt.value = ''
}

async function copiarRespuesta() {
  if (!respuestaPrompt.value) return
  try {
    await navigator.clipboard.writeText(respuestaPrompt.value)
    copiadoExitoso.value = true
    setTimeout(() => {
      copiadoExitoso.value = false
    }, 2000)
  } catch (err) {
    console.error('Error al copiar al portapapeles:', err)
  }
}

function autoScrollResponse() {
  nextTick(() => {
    if (chatScrollContainer.value) {
      chatScrollContainer.value.scrollTop = chatScrollContainer.value.scrollHeight
    }
    if (responseTextarea.value) {
      responseTextarea.value.scrollTop = responseTextarea.value.scrollHeight
    }
  })
}

async function onGenerarInformeChat() {
  if (botonInformeDeshabilitado.value || cargando.value) return
  botonInformeDeshabilitado.value = true
  const params = datosInformeChat.value || {
    codiDistricte: codiDistrictePedido.value,
    zonaPgm: 'densificacio_urbana',
    ubicacion: ubicacionPedida.value,
  }
  if (!params.codiDistricte) return
  if (!params.zonaPgm) {
    params.zonaPgm = params.codiDistricte === 1 ? 'nucli_antic' : 'densificacio_urbana'
  }
  await onGenerar(params)
}

async function onEnviarChat() {
  const mensaje = mensajeChat.value.trim()
  if (!mensaje || procesandoChat.value) return

  botonInformeDeshabilitado.value = true
  procesandoChat.value = true
  datosInformeChat.value = null
  codiDistrictePedido.value = null
  ubicacionPedida.value = null
  articuloSeleccionado.value = null
  reiniciarResultados()

  if (username.value !== null) {
    updateThreadId()
    if (!conversacionSeleccionada.value || conversacionSeleccionada.value === 'nueva conversación') {
      const newThreadId = thread_id.value
      if (!Array.isArray(conversaciones.value)) {
        conversaciones.value = []
      }
      conversaciones.value.push({ id: newThreadId, title: mensaje })
      conversacionSeleccionada.value = newThreadId
      localStorage.setItem('geoyield_conversation', newThreadId)
      log.event('conversation.created', {
        conversation_id: newThreadId,
        title: mensaje,
        user: username.value,
      })
    }

    let primerToken = true
    await assistantStream(mensaje, thread_id.value, {
      onToken: (texto) => {
        if (!texto) return
        if (primerToken) {
          primerToken = false
          const prefijo = respuestaPrompt.value ? `${respuestaPrompt.value.trim()}\n\n` : ''
          respuestaPrompt.value = `${prefijo}PROMPT: ${mensaje}\nRESPONSE:\n`
          mensajeChat.value = ''
        }
        respuestaPrompt.value += texto
        autoScrollResponse()
      },
      onUbicacion: (evento) => {
        if (evento.codi_districte) {
          codiDistrictePedido.value = evento.codi_districte
        }
        if (evento.lat != null && evento.lon != null) {
          ubicacionPedida.value = { lat: evento.lat, lon: evento.lon }
        }
        datosInformeChat.value = {
          codiDistricte: evento.codi_districte,
          zonaPgm: evento.zona_pgm || (evento.codi_districte === 1 ? 'nucli_antic' : 'densificacio_urbana'),
          ubicacion: evento.lat != null && evento.lon != null ? { lat: evento.lat, lon: evento.lon } : null,
        }
        if (evento.codi_districte) {
          botonInformeDeshabilitado.value = false
        }
      },
      onError: (detail) => {
        error.value = detail
        procesandoChat.value = false
      },
      onDone: () => {
        procesandoChat.value = false
      },
    })
    return
  }

  cargando.value = true
  respuestaPrompt.value = ''
  distritoDesdeChat.value = null
  zonaDesdeChat.value = null
  ubicacionDesdeChat.value = null
  mensajeAclaracionChat.value = null
  codiDistrictePedido.value = null
  ubicacionPedida.value = null
  reiniciarResultados()

  let primerTokenChat = true
  await chatInformeStream(mensaje, {
    onAclaracion: (evento) => {
      mensajeAclaracionChat.value = { tipo: 'aviso', texto: evento.mensaje }
      if (evento.lat != null && evento.lon != null) {
        ubicacionDesdeChat.value = { lat: evento.lat, lon: evento.lon }
      }
      const prefijo = respuestaPrompt.value ? `${respuestaPrompt.value.trim()}\n\n` : ''
      respuestaPrompt.value = `${prefijo}AVISO: ${evento.mensaje}`
      autoScrollResponse()
      procesandoChat.value = false
      cargando.value = false
    },
    onUbicacion: (evento) => {
      codiDistrictePedido.value = evento.codi_districte
      if (evento.lat != null && evento.lon != null) {
        ubicacionPedida.value = { lat: evento.lat, lon: evento.lon }
      }
      datosInformeChat.value = {
        codiDistricte: evento.codi_districte,
        zonaPgm: evento.zona_pgm || (evento.codi_districte === 1 ? 'nucli_antic' : 'densificacio_urbana'),
        ubicacion: evento.lat != null && evento.lon != null ? { lat: evento.lat, lon: evento.lon } : null,
      }
      if (evento.codi_districte) {
        botonInformeDeshabilitado.value = false
      }
    },
    onDatos: (evento) => {
      datosDistrito.value = evento.datos_distrito
      respuestaLegal.value = evento.respuesta_legal
      articulosCitados.value = evento.articulos_citados
      cargando.value = false
      // Se mantiene procesandoChat activo mientras llegan los tokens
    },
    onToken: (texto) => {
      if (primerTokenChat) {
        primerTokenChat = false
        const prefijo = respuestaPrompt.value ? `${respuestaPrompt.value.trim()}\n\n` : ''
        respuestaPrompt.value = `${prefijo}PROMPT: ${mensaje}\nRESPONSE:\n`
        mensajeChat.value = ''
      }
      textoSintesis.value += texto
      respuestaPrompt.value += texto
      autoScrollResponse()
    },
    onError: (detail) => {
      error.value = detail
      cargando.value = false
      procesandoChat.value = false
    },
    onDone: (evento) => {
      semaforoConfirmado.value = evento.semaforo
      resumenConfirmado.value = evento.resumen
      cargando.value = false
      procesandoChat.value = false
    },
  })
}
</script>

<template>
  <main class="fondo-plano min-h-screen">
    <div class="mx-auto max-w-[1600px] space-y-8 px-4 py-8 sm:px-6 lg:px-8">
      <!-- Full-Width Header with Métricas Button at the Right End -->
      <header class="flex items-center justify-between gap-4">
        <p class="font-mono text-xs font-bold tracking-[0.2em] text-brass uppercase">Geo-Yield-AI</p>
        <RouterLink
          v-if="usuarioLogueado"
          to="/metrics"
          class="rounded border border-paper/20 px-2.5 py-1 font-mono text-[11px] tracking-wider text-paper/70 uppercase transition hover:border-brass hover:text-brass focus:ring-2 focus:ring-brass/50 focus:outline-none"
        >
          Métricas →
        </RouterLink>
      </header>

      <!-- Full-Width Interactive Chat Panel (previously right column) -->
      <section class="space-y-6 rounded-xl border border-paper/15 bg-ink-light/50 p-6 shadow-lg backdrop-blur-sm">
        <!-- Panel Header -->
        <div class="border-b border-paper/10 pb-4">
          <div class="flex items-center justify-between">
            <p class="font-mono text-xs font-bold tracking-[0.2em] text-brass uppercase">Asistente IA</p>
            <span v-if="procesandoChat" class="flex items-center gap-1.5 font-mono text-xs text-brass animate-pulse">
              <span class="h-2 w-2 animate-ping rounded-full bg-brass" />
              Procesando…
            </span>
            <span
              v-else-if="respuestaPrompt"
              class="rounded bg-[#d1fae5] px-2 py-0.5 font-mono text-xs font-medium text-[#065f46]"
            >
              Respuesta lista
            </span>
            <span v-else class="font-mono text-xs text-paper/40">En espera</span>
          </div>
          <h2 class="mt-1 font-display text-xl font-semibold text-paper">Consulta interactiva</h2>
          <p class="mt-1 text-xs text-paper/60">
            Formula tu consulta en lenguaje natural para evaluar la viabilidad o normativa de tu negocio.
          </p>

          <!-- User Login Line -->
          <div class="mt-3 flex items-center gap-2">
            <label for="user-input" class="shrink-0 font-mono text-xs text-paper/70">user: </label>
            <input
              id="user-input"
              v-model="usuario"
              type="text"
              placeholder="introduce usuario (github username)"
              class="flex-1 rounded border border-paper/20 bg-ink px-3 py-1.5 font-mono text-xs text-paper placeholder:text-paper/30 focus:border-brass focus:ring-1 focus:ring-brass focus:outline-none"
              @keydown.enter.prevent="onLogin"
            />
            <button
              type="button"
              :disabled="!usuario.trim() || cargandoLogin"
              class="shrink-0 rounded bg-brass px-3 py-1.5 text-xs font-medium text-ink transition hover:bg-brass/90 disabled:cursor-not-allowed disabled:opacity-40"
              @click="onLogin"
            >
              {{ cargandoLogin ? 'Verificando…' : 'Login' }}
            </button>
          </div>
          <div v-if="usuarioLogueado" class="mt-1.5 flex items-center gap-1.5 font-mono text-[11px] text-[#065f46]">
            <span class="h-1.5 w-1.5 rounded-full bg-[#065f46]" />
            <span
              >Usuario activo: <strong>{{ usuarioLogueado }}</strong></span
            >
          </div>
          <!-- Conversation Selection Line -->
          <div class="mt-3 flex flex-col gap-1.5">
            <label for="conversation-select" class="font-mono text-xs text-paper/70">
              selecciona para continuar una conversacion:
            </label>
            <select
              id="conversation-select"
              v-model="conversacionSeleccionada"
              class="w-full rounded border border-paper/20 bg-ink px-3 py-1.5 font-mono text-xs text-paper focus:border-brass focus:ring-1 focus:ring-brass focus:outline-none"
              @change="onSeleccionarConversacion"
            >
              <option value="">nueva conversación</option>
              <option v-for="c in conversaciones" :key="c.id" :value="c.id">
                {{ c.title }}
              </option>
            </select>
          </div>
        </div>

        <!-- CONVERSATION / RESPONSE DISPLAY (ARRIBA) -->
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <label class="text-xs font-medium tracking-wide text-paper/70 uppercase">
              Conversación / Respuesta del Asistente
            </label>
            <div class="flex items-center gap-2">
              <button
                v-if="respuestaPrompt"
                type="button"
                class="text-xs text-paper/50 transition hover:text-paper"
                @click="limpiarRespuesta"
              >
                Limpiar
              </button>
              <button
                v-if="respuestaPrompt"
                type="button"
                class="flex items-center gap-1 rounded border border-paper/20 px-2 py-0.5 text-xs text-brass transition hover:bg-brass/10"
                @click="copiarRespuesta"
              >
                {{ copiadoExitoso ? '✓ Copiado' : 'Copiar' }}
              </button>
            </div>
          </div>

          <!-- Message Bubbles Container -->
          <div
            ref="chatScrollContainer"
            class="flex max-h-[460px] min-h-[160px] flex-col gap-3 overflow-y-auto rounded-lg border border-paper/20 bg-ink p-4"
          >
            <div v-if="listaMensajesChat.length === 0" class="flex h-full items-center justify-center py-8 text-center">
              <p class="font-mono text-xs text-paper/30">La respuesta del asistente aparecerá aquí en tiempo real...</p>
            </div>

            <template v-else>
              <div
                v-for="(msg, idx) in listaMensajesChat"
                :key="idx"
                class="flex w-full"
                :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
              >
                <!-- User Message Bubble (ALINEADO A LA DERECHA) -->
                <div
                  v-if="msg.role === 'user'"
                  class="max-w-[85%] rounded-2xl rounded-tr-sm bg-brass/20 border border-brass/40 px-4 py-2.5 text-right shadow-sm sm:max-w-[75%]"
                >
                  <p class="font-mono text-[10px] font-semibold tracking-wider text-brass uppercase mb-1">
                    Tú (Consulta)
                  </p>
                  <p class="text-xs text-paper whitespace-pre-wrap leading-relaxed">
                    {{ msg.text }}
                  </p>
                </div>

                <!-- Assistant Response Bubble (ALINEADO A LA IZQUIERDA) -->
                <div
                  v-else
                  class="max-w-[90%] rounded-2xl rounded-tl-sm border border-paper/20 bg-ink-light px-4 py-3 text-left shadow-sm sm:max-w-[85%]"
                >
                  <div class="flex items-center gap-2 mb-1.5 border-b border-paper/10 pb-1">
                    <span
                      class="flex h-5 w-5 items-center justify-center rounded-full bg-brass text-[10px] font-bold text-ink"
                    >
                      GY
                    </span>
                    <span class="font-mono text-[10px] font-semibold tracking-wider text-brass uppercase">
                      GeoYield Asistente
                    </span>
                  </div>
                  <p class="font-mono text-xs text-paper/90 whitespace-pre-wrap leading-relaxed">
                    {{ msg.text }}
                  </p>
                </div>
              </div>
            </template>
          </div>

          <!-- Citations Pills -->
          <div v-if="articulosCitados.length > 0" class="pt-1">
            <p class="mb-1.5 font-mono text-[10px] font-semibold tracking-wider text-brass uppercase">
              Artículos legales citados:
            </p>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="articulo in articulosCitados"
                :key="`${articulo.fuente_legal}-${articulo.numero_articulo}`"
                type="button"
                class="flex items-center gap-1.5 rounded-full border border-brass/30 bg-brass/10 px-3 py-1 font-mono text-xs text-brass transition-all hover:bg-brass hover:text-ink hover:shadow-md focus:ring-2 focus:ring-brass focus:outline-none"
                title="Abrir visor de normativa"
                @click="articuloSeleccionado = articulo"
              >
                Art. {{ articulo.numero_articulo }}
              </button>
            </div>
          </div>
        </div>

        <!-- PROMPT / CONSULTA INPUT BOX (ABAJO) -->
        <div class="space-y-2 border-t border-paper/10 pt-4">
          <div class="flex items-center justify-between">
            <label for="prompt-input" class="text-xs font-medium tracking-wide text-paper/70 uppercase">
              Prompt / Consulta
            </label>
            <button
              v-if="mensajeChat"
              type="button"
              class="text-xs text-paper/50 transition hover:text-paper"
              @click="limpiarPrompt"
            >
              Limpiar
            </button>
          </div>

          <textarea
            id="prompt-input"
            v-model="mensajeChat"
            rows="3"
            placeholder="p. ej. Quiero abrir un bar en Carrer de Sant Pau 1, ¿me lo recomiendas?"
            class="w-full resize-y rounded-lg border border-paper/20 bg-ink px-3.5 py-2.5 text-sm text-paper placeholder:text-paper/30 focus:border-brass focus:ring-1 focus:ring-brass focus:outline-none"
            @keydown.enter.exact.prevent="onEnviarChat"
          />

          <div class="flex items-center justify-between gap-2 pt-1">
            <span class="text-[11px] text-paper/40">Enter para enviar &middot; Shift+Enter para nueva línea</span>
            <div class="flex items-center gap-2">
              <button
                type="button"
                :disabled="botonInformeDeshabilitado || cargando"
                class="flex shrink-0 items-center gap-2 rounded px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40"
                :class="
                  botonInformeDeshabilitado || cargando
                    ? 'border border-brass/30 bg-brass/10 text-brass'
                    : 'bg-brass text-ink shadow-md hover:bg-brass/90 ring-1 ring-brass'
                "
                @click="onGenerarInformeChat"
              >
                <span
                  v-if="cargando && !tieneResultados"
                  class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
                />
                <span>{{ cargando && !tieneResultados ? 'Generando…' : 'Generar Informe' }}</span>
              </button>
              <button
                type="button"
                :disabled="procesandoChat || !mensajeChat.trim()"
                class="flex shrink-0 items-center gap-2 rounded bg-brass px-4 py-2 text-sm font-medium text-ink transition hover:bg-brass/90 disabled:cursor-not-allowed disabled:opacity-40"
                @click="onEnviarChat"
              >
                <span
                  v-if="procesandoChat"
                  class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-ink border-t-transparent"
                />
                <span>{{ procesandoChat ? 'Analizando…' : 'Enviar' }}</span>
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- Error Alert Banner -->
      <div
        v-if="error"
        class="flex items-center gap-3 rounded-lg border border-rojo/40 bg-rojo/10 px-5 py-4 text-sm text-paper shadow-sm"
      >
        {{ error }}
      </div>

      <!-- Loading Indicator -->
      <div
        v-if="cargando && !tieneResultados"
        class="flex items-center justify-center gap-3 py-12 text-sm text-paper/60"
      >
        <span class="h-2.5 w-2.5 animate-ping rounded-full bg-brass" />
        Consultando la normativa y analizando datos del distrito...
      </div>

      <!-- Results Section -->
      <section v-if="tieneResultados" class="animate-fade-in space-y-6">
        <VerdictCard v-if="semaforo" :informe="{ semaforo, resumen, datos_distrito: datosDistrito || {} }" />
        <div
          v-else
          class="flex items-center gap-3 rounded-xl border border-paper/15 bg-paper px-6 py-5 text-sm text-ink/60 shadow-sm"
        >
          <span class="h-2 w-2 animate-ping rounded-full bg-brass" />
          Generando el veredicto…
        </div>

        <div class="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <DistrictMap
            v-if="datosDistrito"
            class="h-full min-h-[300px] overflow-hidden rounded-xl border border-paper/15 shadow-sm"
            :codi-districte="codiDistrictePedido"
            :nom-districte="datosDistrito.nom_districte"
            :ubicacion="ubicacionPedida"
          />

          <ChatBubble
            v-if="respuestaLegal"
            :informe="{ respuesta_legal: respuestaLegal, articulos_citados: articulosCitados }"
            @ver-articulo="articuloSeleccionado = $event"
          />
        </div>
      </section>
    </div>

    <!-- Legal Article Modal Viewer -->
    <RegulationsViewer :articulo="articuloSeleccionado" @cerrar="articuloSeleccionado = null" />
  </main>
</template>

<style>
@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
.animate-fade-in {
  animation: fadeIn 0.4s ease-out forwards;
}
</style>
