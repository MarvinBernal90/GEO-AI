<!--
==============================================================================
LEGAL ARTICLE VIEWER (INSIDE THE NORMATIVA PANEL)
==============================================================================
File: frontend/src/components/RegulationsViewer.vue

Fetches and shows the full text of one legal article, inside the dark legal
panel. Crucial for AI verifiability: it lets users compare the LLM's summary
with the raw text stored in PostgreSQL. "Cerrar" here means "back to the list".
-->
<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { obtenerArticulo } from '../services/api.js'
import { createLogger } from '../services/logger.js'

const log = createLogger('component.visor-normativa')

const props = defineProps({
  articulo: { type: Object, default: null },
})
const emit = defineEmits(['cerrar'])

const cargando = ref(false)
const error = ref(null)
const detalle = ref(null)

// Accessibility: Escape goes back to the list of articles
const manejarTeclado = (e) => {
  if (e.key === 'Escape' && props.articulo) emit('cerrar')
}

// Memory Leak Prevention:
// Global event listeners MUST be explicitly removed when the component unmounts.
onMounted(() => document.addEventListener('keydown', manejarTeclado))
onUnmounted(() => document.removeEventListener('keydown', manejarTeclado))

// Fetch the article details dynamically from the API whenever the 'articulo' prop changes
watch(
  () => props.articulo,
  async (nuevo) => {
    if (!nuevo) {
      detalle.value = null
      return
    }
    cargando.value = true
    error.value = null
    detalle.value = null

    try {
      detalle.value = await obtenerArticulo(nuevo.fuente_legal, nuevo.numero_articulo)
      log.event('articulo.abierto', {
        fuente_legal: nuevo.fuente_legal,
        numero_articulo: nuevo.numero_articulo,
      })
    } catch (err) {
      // A cited article that cannot be opened points to a hallucinated
      // citation or a stale legal corpus, so it is worth recording.
      log.error('Could not load the legal article', {
        error: err,
        fuente_legal: nuevo.fuente_legal,
        numero_articulo: nuevo.numero_articulo,
        status: err?.status,
      })
      error.value = err.message
    } finally {
      cargando.value = false
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="space-y-4 px-4 py-4">
    <button
      type="button"
      class="rounded-md px-1 py-0.5 text-xs text-paper/60 transition hover:text-paper focus-visible:ring-2 focus-visible:ring-brass focus-visible:outline-none"
      @click="emit('cerrar')"
    >
      ← Volver a la lista
    </button>

    <p class="font-mono text-[10px] tracking-widest text-paper/50 uppercase">
      Artículo {{ articulo?.numero_articulo }}
    </p>

    <!-- Skeleton Loading State -->
    <div v-if="cargando" class="animate-pulse space-y-4" aria-busy="true">
      <div class="h-3 w-1/3 rounded bg-paper/10"></div>
      <div class="h-5 w-2/3 rounded bg-paper/10"></div>
      <div class="space-y-2 pt-3">
        <div class="h-3.5 w-full rounded bg-paper/10"></div>
        <div class="h-3.5 w-5/6 rounded bg-paper/10"></div>
        <div class="h-3.5 w-4/6 rounded bg-paper/10"></div>
      </div>
    </div>

    <div
      v-else-if="error"
      class="rounded-lg border border-rojo/40 bg-rojo/10 px-3 py-2.5 text-sm text-paper"
      role="alert"
    >
      <span class="font-semibold text-rojo">Error:</span> {{ error }}
    </div>

    <!-- Parsed Legal Text -->
    <article v-else-if="detalle" class="space-y-3">
      <p class="inline-block rounded bg-brass/10 px-2 py-1 font-mono text-[11px] text-brass">
        {{ detalle.fuente_legal }}
      </p>
      <h3 class="font-display text-base font-medium text-paper">{{ detalle.titulo }}</h3>
      <p class="text-sm leading-relaxed whitespace-pre-line text-paper/80">{{ detalle.contenido }}</p>
    </article>
  </div>
</template>
