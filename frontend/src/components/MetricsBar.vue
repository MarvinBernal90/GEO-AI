<!--
==============================================================================
METRICS BAR (TOP OF THE PAGE)
==============================================================================
File: frontend/src/components/MetricsBar.vue

Slim bar with the live numbers of the last query: tokens, time, time to first
token, cost, model and state. It is always visible and starts at zero. The
button opens the pipeline panel with the step-by-step detail.
Presentational: all numbers come from useTrace().
-->
<script setup>
import { computed } from 'vue'

import { formatearEuros, formatearNumero, formatearTiempo } from '../composables/useTrace.js'

const props = defineProps({
  traza: { type: Object, required: true },
  pipelineAbierto: { type: Boolean, default: false },
})

const emit = defineEmits(['toggle-pipeline'])

const ESTADOS = {
  espera: { texto: 'En espera', punto: 'bg-paper/30' },
  procesando: { texto: 'Procesando', punto: 'bg-brass animate-pulse motion-reduce:animate-none' },
  completado: { texto: 'Completado', punto: 'bg-verde' },
  error: { texto: 'Con error', punto: 'bg-rojo' },
}

const estado = computed(() => ESTADOS[props.traza.estado] ?? ESTADOS.espera)

const celdas = computed(() => {
  const t = props.traza.totales
  return [
    {
      clave: 'tokens',
      etiqueta: 'Tokens',
      valor: `${formatearNumero(t.tokensIn)} ent. / ${formatearNumero(t.tokensOut)} sal.`,
      ayuda: 'Tokens enviados al modelo y tokens generados',
    },
    {
      clave: 'tiempo',
      etiqueta: 'Tiempo',
      valor: formatearTiempo(t.elapsedMs),
      ayuda: 'Duración total de la consulta',
    },
    {
      clave: 'ttft',
      etiqueta: '1.er token',
      valor: t.ttftMs == null ? '—' : formatearTiempo(t.ttftMs),
      ayuda: 'Tiempo hasta que empieza a llegar la respuesta',
    },
    {
      clave: 'coste',
      etiqueta: 'Coste',
      valor: t.sinTarifa ? 'sin tarifa' : formatearEuros(t.costeEur),
      ayuda: t.sinTarifa
        ? 'El modelo se usó, pero no hay tarifa configurada para calcular el coste'
        : 'Coste estimado de la consulta en euros',
    },
    {
      clave: 'modelo',
      etiqueta: 'Modelo',
      valor: t.modelos.join(', ') || '—',
      ayuda: 'Modelo de lenguaje usado',
    },
  ]
})
</script>

<template>
  <header
    class="flex h-10 items-center gap-6 overflow-x-auto border-b border-paper/10 bg-ink px-4 text-xs whitespace-nowrap"
    aria-label="Métricas de la consulta"
  >
    <div v-for="celda in celdas" :key="celda.clave" class="flex items-baseline gap-2" :title="celda.ayuda">
      <span class="font-mono text-[10px] tracking-wider text-paper/50 uppercase">{{ celda.etiqueta }}</span>
      <span class="max-w-[14rem] truncate font-medium text-paper tabular-nums">{{ celda.valor }}</span>
    </div>

    <div class="ml-auto flex items-center gap-4">
      <span class="flex items-center gap-2 text-paper/70" role="status">
        <span class="h-2 w-2 rounded-full" :class="estado.punto" />
        {{ estado.texto }}
      </span>
      <button
        type="button"
        class="rounded-md border border-paper/15 px-2.5 py-1 text-paper/80 transition hover:text-paper focus-visible:ring-2 focus-visible:ring-brass focus-visible:outline-none"
        :aria-expanded="pipelineAbierto"
        @click="emit('toggle-pipeline')"
      >
        Pipeline<span v-if="traza.hayDatos"> · {{ traza.pasos.length }}</span>
        {{ pipelineAbierto ? '▴' : '▾' }}
      </button>
    </div>
  </header>
</template>
