<!--
==============================================================================
REPORT MESSAGE (A REPORT INSIDE THE CHAT)
==============================================================================
File: frontend/src/components/ReportMessage.vue

Presentational component. Draws one report as the assistant's answer: the
verdict card (traffic light + summary + district data) and one button that
opens the legal panel (cited articles and legal basis live there, not here).
The summary text appears only once, inside the verdict card.
-->
<script setup>
import { computed } from 'vue'

import { resumenDe, semaforoDe } from '../composables/useChat.js'
import VerdictCard from './VerdictCard.vue'

const props = defineProps({
  report: { type: Object, required: true },
})

// Same event name as before: with no payload it just opens the legal panel.
const emit = defineEmits(['ver-articulo'])

const semaforo = computed(() => semaforoDe(props.report))
const informe = computed(() => ({
  semaforo: semaforo.value,
  resumen: resumenDe(props.report),
  datos_distrito: props.report.datos ?? {},
}))

const esperando = computed(() => props.report.status === 'cargando')
const mostrarContenido = computed(() => props.report.status !== 'error' || props.report.datos !== null)
const totalArticulos = computed(() => props.report.articulos.length)
const hayNormativa = computed(() => totalArticulos.value > 0 || Boolean(props.report.respuestaLegal))
const etiquetaNormativa = computed(() => {
  if (!totalArticulos.value) return 'Ver normativa aplicable'
  const palabra = totalArticulos.value === 1 ? 'artículo' : 'artículos'
  return `Ver normativa aplicable · ${totalArticulos.value} ${palabra}`
})
</script>

<template>
  <div class="w-full space-y-3">
    <div
      v-if="report.status === 'error'"
      class="rounded-lg border border-rojo/40 bg-rojo/10 px-4 py-3 text-sm text-paper"
      role="alert"
    >
      {{ report.error || 'No se pudo generar el informe.' }}
    </div>

    <template v-if="mostrarContenido">
      <div
        v-if="esperando"
        class="flex items-center gap-2.5 rounded-lg border border-paper/10 bg-ink-light px-4 py-3 text-sm text-paper/70"
      >
        <span class="h-2 w-2 animate-ping rounded-full bg-brass motion-reduce:animate-none" />
        Consultando la normativa y analizando los datos del distrito…
      </div>

      <template v-else>
        <VerdictCard v-if="semaforo" :informe="informe" />
        <div
          v-else-if="report.status === 'detenido'"
          class="rounded-lg border border-paper/10 bg-ink-light px-4 py-3 text-sm text-paper/70"
        >
          Informe detenido antes de terminar.
        </div>
        <div
          v-else-if="report.status !== 'error'"
          class="flex items-center gap-2.5 rounded-xl border border-paper/10 bg-ink-light px-5 py-4 text-sm text-paper/60"
        >
          <span class="h-2 w-2 animate-ping rounded-full bg-brass motion-reduce:animate-none" />
          Generando el veredicto…
        </div>

        <button
          v-if="hayNormativa"
          type="button"
          class="flex w-full items-center justify-between gap-3 rounded-lg border border-paper/10 bg-ink-light px-4 py-2.5 text-left text-xs text-paper/80 transition hover:border-brass/50 hover:text-paper focus-visible:ring-2 focus-visible:ring-brass focus-visible:outline-none"
          @click="emit('ver-articulo', null)"
        >
          <span>{{ etiquetaNormativa }}</span>
          <span aria-hidden="true" class="text-brass">→</span>
        </button>
      </template>
    </template>
  </div>
</template>
