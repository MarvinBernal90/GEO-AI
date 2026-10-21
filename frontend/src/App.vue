<!--
==============================================================================
ROOT COMPONENT & LAYOUT
==============================================================================
File: frontend/src/App.vue

Main Vue component. A metrics bar on top and, below it, full-height panes:
- Left: the unified chat (messages, reports, message box, guided search).
- Middle (optional): the legal panel of the last report. On wide screens it is
  a column that opens by itself when a report arrives; on narrower screens it
  opens over the map when the user asks for it.
- Right: the map, which follows the last report of the conversation.
The pipeline panel (steps of the last query) drops over the map from the bar.

State lives in composables:
- useSession: user, login, conversations and thread id.
- useChat: the conversation, including every report as a message.
- useTrace: metrics and steps of the last query, built from the trace events.
-->
<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import ChatPanel from './components/ChatPanel.vue'
import DistrictMap from './components/DistrictMap.vue'
import MetricsBar from './components/MetricsBar.vue'
import NormativaPanel from './components/NormativaPanel.vue'
import PipelinePanel from './components/PipelinePanel.vue'
import ViabilityForm from './components/ViabilityForm.vue'
import { useChat } from './composables/useChat.js'
import { useSession } from './composables/useSession.js'
import { useTrace } from './composables/useTrace.js'
import { getHistory } from './services/api.js'
import { createLogger } from './services/logger.js'

const log = createLogger('app')

const articuloSeleccionado = ref(null)
const guidedOpen = ref(false)
const normativaAbierta = ref(false)
const pipelineAbierto = ref(false)

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
// Values the chat sends to the guided form so it can pre-fill itself when the
// backend needs a clarification (e.g. only the district was understood).
const distritoDesdeChat = ref(null)
const zonaDesdeChat = ref(null)
const ubicacionDesdeChat = ref(null)
const mensajeAclaracionChat = ref(null)

const { messages, sending, lastReport, traceEvents, send, sendGuided, cancel, clear, loadHistory } = useChat({
  getThreadId: () => threadId.value,
  onStart: () => {
    distritoDesdeChat.value = null
    zonaDesdeChat.value = null
    ubicacionDesdeChat.value = null
    mensajeAclaracionChat.value = null
  },
  onAclaracion: (evento) => {
    mensajeAclaracionChat.value = { tipo: 'aviso', texto: evento.mensaje }
    if (evento.codi_districte) distritoDesdeChat.value = evento.codi_districte
    if (evento.zona_pgm) zonaDesdeChat.value = evento.zona_pgm
    if (evento.lat != null && evento.lon != null) {
      ubicacionDesdeChat.value = { lat: evento.lat, lon: evento.lon }
    }
    guidedOpen.value = true
  },
})

// Metrics and steps of the last query (zero until the first one).
const { traza } = useTrace({ eventos: traceEvents, enCurso: sending })

// The map follows the last report; without reports it shows the whole city.
const mapa = computed(() => {
  const report = lastReport.value
  return {
    codi: report?.codiDistricte ?? null,
    nombre: report?.datos?.nom_districte ?? '',
    ubicacion: report?.ubicacion ?? null,
  }
})

// ---------------------------------------------------------------------------
// LEGAL PANEL
// ---------------------------------------------------------------------------
// Wide screens (>= 1280 px) have room for a third column; narrower ones show
// the panel over the map. Only one of the two is ever rendered.
const pantallaAncha = window.matchMedia('(min-width: 1280px)')
const esAncha = ref(pantallaAncha.matches)
const alCambiarAncho = (e) => {
  esAncha.value = e.matches
}
onMounted(() => pantallaAncha.addEventListener('change', alCambiarAncho))
onBeforeUnmount(() => pantallaAncha.removeEventListener('change', alCambiarAncho))

const hayNormativa = computed(() => {
  const report = lastReport.value
  return Boolean(report && (report.respuestaLegal || report.articulos?.length))
})
const mostrarColumna = computed(() => normativaAbierta.value && hayNormativa.value && esAncha.value)
const mostrarSuperpuesta = computed(() => normativaAbierta.value && hayNormativa.value && !esAncha.value)

/** Opens the panel; with an article it goes straight to its full text. */
function abrirNormativa(articulo = null) {
  articuloSeleccionado.value = articulo
  normativaAbierta.value = true
}

function cerrarNormativa() {
  normativaAbierta.value = false
  articuloSeleccionado.value = null
}

// Open by itself on wide screens when a report is ready; close when the chat is cleared.
watch(
  () => lastReport.value?.status,
  (status) => {
    if (!status) {
      cerrarNormativa()
      return
    }
    if (status === 'listo' && hayNormativa.value && esAncha.value) abrirNormativa()
  },
)

// ---------------------------------------------------------------------------
// ACTIONS
// ---------------------------------------------------------------------------
async function onEnviarChat(texto) {
  ensureConversation(texto)
  await send(texto)
}

async function onGenerar(params) {
  guidedOpen.value = false
  await sendGuided(params)
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
  <!-- The metrics bar is 2.5 rem tall, so the panes use 100vh minus that -->
  <main class="min-h-screen bg-ink lg:h-screen lg:overflow-hidden">
    <MetricsBar
      :traza="traza"
      :pipeline-abierto="pipelineAbierto"
      @toggle-pipeline="pipelineAbierto = !pipelineAbierto"
    />

    <div class="relative lg:flex">
      <!-- LEFT PANE: unified chat -->
      <div class="h-[88vh] min-h-0 lg:h-[calc(100vh-2.5rem)] lg:w-[clamp(400px,34vw,520px)] lg:shrink-0">
        <ChatPanel
          v-model:usuario="usuario"
          v-model:conversacion="conversacionSeleccionada"
          v-model:guided-open="guidedOpen"
          :messages="messages"
          :sending="sending"
          :username="username"
          :logging-in="cargandoLogin"
          :login-error="loginError"
          :conversations="conversaciones"
          @login="login"
          @send="onEnviarChat"
          @cancel="cancel"
          @clear="clear"
          @select-conversation="onSeleccionarConversacion"
          @ver-articulo="abrirNormativa"
        >
          <template #guided>
            <ViabilityForm
              :cargando="sending"
              :distrito-inicial="distritoDesdeChat"
              :zona-inicial="zonaDesdeChat"
              :ubicacion-inicial="ubicacionDesdeChat"
              :mensaje-inicial="mensajeAclaracionChat"
              @generar="onGenerar"
            />
          </template>
        </ChatPanel>
      </div>

      <!-- MIDDLE PANE (wide screens): legal column -->
      <aside v-if="mostrarColumna" class="h-[calc(100vh-2.5rem)] w-80 shrink-0 border-x border-paper/10">
        <NormativaPanel
          :report="lastReport"
          :articulo="articuloSeleccionado"
          @cerrar="cerrarNormativa"
          @seleccionar="articuloSeleccionado = $event"
        />
      </aside>

      <!-- RIGHT PANE: map -->
      <div class="relative h-[70vh] min-h-0 lg:h-[calc(100vh-2.5rem)] lg:min-w-0 lg:flex-1">
        <DistrictMap
          class="h-full"
          :codi-districte="mapa.codi"
          :nom-districte="mapa.nombre"
          :ubicacion="mapa.ubicacion"
        />

        <!-- Legal panel over the map (narrow screens) -->
        <div
          v-if="mostrarSuperpuesta"
          class="absolute inset-y-0 left-0 z-20 w-[min(92%,22rem)] border-r border-paper/10 shadow-2xl"
        >
          <NormativaPanel
            :report="lastReport"
            :articulo="articuloSeleccionado"
            @cerrar="cerrarNormativa"
            @seleccionar="articuloSeleccionado = $event"
          />
        </div>

        <!-- Tab to reopen the legal panel on wide screens after closing it -->
        <button
          v-if="hayNormativa && !normativaAbierta && esAncha"
          type="button"
          class="absolute top-1/2 left-0 z-20 -translate-y-1/2 rounded-r-lg border border-l-0 border-paper/10 bg-ink/90 px-2 py-4 text-xs text-paper/80 [writing-mode:vertical-rl] transition hover:text-paper focus-visible:ring-2 focus-visible:ring-brass focus-visible:outline-none"
          @click="abrirNormativa()"
        >
          Normativa
        </button>
      </div>

      <!-- Pipeline panel: drops from the metrics bar, over the map -->
      <div v-if="pipelineAbierto" class="absolute top-3 right-3 z-30 w-[min(640px,calc(100%-1.5rem))]">
        <PipelinePanel :traza="traza" @cerrar="pipelineAbierto = false" />
      </div>
    </div>
  </main>
</template>
