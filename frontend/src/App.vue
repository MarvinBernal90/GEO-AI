<!--
==============================================================================
ROOT COMPONENT & STATE ORCHESTRATOR
==============================================================================
File: frontend/src/App.vue

Main Vue component. It owns the report state (district data, legal answer,
verdict) and connects the pieces:
- useSession: user, login, conversations and thread id.
- useChat: the unified chat (bubbles + events of the stream).
Layout:
- Left column: dossier header, viability form, verdict card, district map and
  legal basis.
- Right column: the chat panel.
-->
<script setup>
import { computed, ref } from 'vue'
import ViabilityForm from './components/ViabilityForm.vue'
import VerdictCard from './components/VerdictCard.vue'
import ChatBubble from './components/ChatBubble.vue'
import ChatPanel from './components/ChatPanel.vue'
import DistrictMap from './components/DistrictMap.vue'
import RegulationsViewer from './components/RegulationsViewer.vue'
import { useChat } from './composables/useChat.js'
import { useSession } from './composables/useSession.js'
import { generarInformeStream, getHistory } from './services/api.js'
import { createLogger } from './services/logger.js'

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
// SESSION (user, conversations, thread id)
// ---------------------------------------------------------------------------
const {
  usuario,
  username,
  loginError,
  cargandoLogin,
  conversaciones,
  conversacionSeleccionada,
  esNueva,
  threadId,
  login,
  ensureConversation,
  persistSelection,
} = useSession()

// ---------------------------------------------------------------------------
// UNIFIED CHAT
// ---------------------------------------------------------------------------
// Values the chat sends to the form so it can pre-fill itself when the backend
// needs a clarification (e.g. only the district was understood).
const distritoDesdeChat = ref(null)
const zonaDesdeChat = ref(null)
const ubicacionDesdeChat = ref(null)
const mensajeAclaracionChat = ref(null)

const { messages, sending, send, cancel, clear, loadHistory } = useChat({
  getThreadId: () => threadId.value,
  onStart: () => {
    distritoDesdeChat.value = null
    zonaDesdeChat.value = null
    ubicacionDesdeChat.value = null
    mensajeAclaracionChat.value = null
    error.value = null
  },
  onAclaracion: (evento) => {
    mensajeAclaracionChat.value = { tipo: 'aviso', texto: evento.mensaje }
    if (evento.codi_districte) distritoDesdeChat.value = evento.codi_districte
    if (evento.zona_pgm) zonaDesdeChat.value = evento.zona_pgm
    if (evento.lat != null && evento.lon != null) {
      ubicacionDesdeChat.value = { lat: evento.lat, lon: evento.lon }
    }
    cargando.value = false
  },
  onUbicacion: (evento) => {
    // A new report starts: clear the previous one and show the loading state.
    reiniciarResultados()
    cargando.value = true
    codiDistrictePedido.value = evento.codi_districte
    ubicacionPedida.value = { lat: evento.lat, lon: evento.lon }
  },
  onDatos: (evento) => {
    datosDistrito.value = evento.datos_distrito
    respuestaLegal.value = evento.respuesta_legal
    articulosCitados.value = evento.articulos_citados
    cargando.value = false
  },
  onToken: (texto) => {
    textoSintesis.value += texto
  },
  onDone: (evento) => {
    semaforoConfirmado.value = evento.semaforo
    resumenConfirmado.value = evento.resumen
    cargando.value = false
  },
  onError: () => {
    cargando.value = false
  },
  onCancel: () => {
    cargando.value = false
  },
})

async function onEnviarChat(texto) {
  ensureConversation(texto)
  await send(texto)
}

async function onSeleccionarConversacion() {
  clear()
  persistSelection()
  if (esNueva.value) return

  try {
    const data = await getHistory(threadId.value)
    if (data && typeof data.content === 'string') loadHistory(data.content)
  } catch (err) {
    log.error('Failed to load conversation history', {
      thread_id: threadId.value,
      error: err.message,
    })
  }
}
</script>

<template>
  <main class="fondo-plano min-h-screen">
    <div class="mx-auto max-w-[1600px] px-4 py-8 sm:px-6 lg:px-8">
      <!-- Responsive 2-column layout: left for the report, right for the chat -->
      <div class="grid grid-cols-1 items-start gap-8 lg:grid-cols-12">
        <!-- LEFT COLUMN: Actual Contents -->
        <div class="space-y-8 lg:col-span-7 xl:col-span-7">
          <header class="text-center sm:text-left">
            <p class="mb-2 font-mono text-xs font-bold tracking-[0.2em] text-brass uppercase">Geo-Yield-AI</p>
            <h1 class="font-display text-3xl font-semibold text-paper sm:text-4xl xl:text-5xl">
              Dossier de viabilidad de hostelería
            </h1>
            <p class="mt-4 text-sm leading-relaxed text-paper/70 sm:text-base">
              Selecciona un distrito y una zona urbanística de Barcelona para generar un informe que cruza la normativa
              legal vigente con datos socioeconómicos reales.
            </p>
          </header>

          <!-- Viability Form Section -->
          <section class="rounded-xl border border-paper/15 bg-ink-light/50 p-6 shadow-lg backdrop-blur-sm">
            <ViabilityForm
              :cargando="cargando"
              :distrito-inicial="distritoDesdeChat"
              :zona-inicial="zonaDesdeChat"
              :ubicacion-inicial="ubicacionDesdeChat"
              :mensaje-inicial="mensajeAclaracionChat"
              @generar="onGenerar"
            />
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

        <!-- RIGHT COLUMN: unified chat -->
        <div class="lg:col-span-5 xl:col-span-5">
          <aside class="lg:sticky lg:top-8">
            <ChatPanel
              v-model:usuario="usuario"
              v-model:conversacion="conversacionSeleccionada"
              :messages="messages"
              :sending="sending"
              :username="username"
              :logging-in="cargandoLogin"
              :login-error="loginError"
              :conversations="conversaciones"
              :articles="articulosCitados"
              @login="login"
              @send="onEnviarChat"
              @cancel="cancel"
              @clear="clear"
              @select-conversation="onSeleccionarConversacion"
              @ver-articulo="articuloSeleccionado = $event"
            />
          </aside>
        </div>
      </div>
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
