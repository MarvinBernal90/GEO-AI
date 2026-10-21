<!--
==============================================================================
PIPELINE PANEL (LANES + STEP LOG)
==============================================================================
File: frontend/src/components/PipelinePanel.vue

Shows how the last query ran:
- one lane per actor (Agente, LLM, RAG, Base de datos, Externo) on a shared
  time axis; running steps pulse,
- a step-by-step log, indented by parent, with duration, tokens and model;
  click a step with extra detail to see its input/output summary.
Presentational: all data comes from useTrace().
-->
<script setup>
import { computed, ref } from 'vue'

import { formatearNumero, formatearTiempo } from '../composables/useTrace.js'

const props = defineProps({
  traza: { type: Object, required: true },
})

const emit = defineEmits(['cerrar'])

// Which log rows are expanded (by step id)
const abiertos = ref({})
function alternar(id) {
  abiertos.value = { ...abiertos.value, [id]: !abiertos.value[id] }
}

const marcas = computed(() => [0, 0.25, 0.5, 0.75, 1].map((f) => formatearTiempo(props.traza.duracionEjeMs * f)))
</script>

<template>
  <section
    class="flex max-h-[calc(100vh-4rem)] flex-col overflow-hidden rounded-xl border border-paper/10 bg-ink-light text-paper shadow-2xl"
    aria-label="Pipeline de la consulta"
  >
    <header class="flex items-center justify-between gap-3 border-b border-paper/10 px-4 py-3">
      <div>
        <p class="font-mono text-[10px] tracking-widest text-paper/50 uppercase">Pipeline de la consulta</p>
        <p class="text-sm text-paper/80">
          {{ traza.pasos.length }} pasos · {{ formatearTiempo(traza.totales.elapsedMs) }}
        </p>
      </div>
      <button
        type="button"
        class="rounded-full px-2.5 py-1 text-base text-paper/50 transition-colors hover:bg-paper/10 hover:text-paper focus-visible:ring-2 focus-visible:ring-brass focus-visible:outline-none"
        aria-label="Cerrar pipeline"
        @click="emit('cerrar')"
      >
        ✕
      </button>
    </header>

    <div class="min-h-0 flex-1 overflow-y-auto px-4 py-3">
      <p v-if="!traza.hayDatos" class="py-6 text-center text-sm text-paper/60">
        Aún no hay datos. Envía una consulta y aquí verás cada paso, en vivo.
      </p>

      <template v-else>
        <!-- Lanes -->
        <div class="space-y-1.5">
          <div
            v-for="carril in traza.carriles"
            :key="carril.clave"
            class="grid grid-cols-[6.5rem_1fr] items-center gap-3"
          >
            <div class="min-w-0">
              <p class="truncate text-xs" :style="{ color: carril.color }">{{ carril.label }}</p>
              <p class="text-[10px] text-paper/50">{{ carril.llamadas }} · {{ formatearTiempo(carril.ocupadoMs) }}</p>
            </div>
            <div class="relative h-5 rounded bg-paper/5">
              <div
                v-for="paso in carril.pasos"
                :key="paso.id"
                class="absolute top-0.5 bottom-0.5 rounded-sm"
                :class="{ 'animate-pulse motion-reduce:animate-none': paso.enMarcha }"
                :style="{ left: `${paso.izq}%`, width: `${paso.ancho}%`, backgroundColor: carril.color }"
                :title="`${paso.etiqueta} · ${formatearTiempo(paso.dur)}`"
              />
            </div>
          </div>

          <div class="grid grid-cols-[6.5rem_1fr] gap-3">
            <span />
            <div class="flex justify-between text-[10px] text-paper/40">
              <span v-for="(marca, i) in marcas" :key="i">{{ marca }}</span>
            </div>
          </div>
        </div>

        <!-- Step by step -->
        <h3 class="mt-5 mb-2 font-mono text-[10px] font-semibold tracking-widest text-brass uppercase">Paso a paso</h3>
        <ol class="space-y-0.5">
          <li v-for="fila in traza.filas" :key="fila.id">
            <component
              :is="fila.detalle ? 'button' : 'div'"
              v-bind="
                fila.detalle
                  ? { type: 'button', 'aria-expanded': Boolean(abiertos[fila.id]), onClick: () => alternar(fila.id) }
                  : {}
              "
              class="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-paper/5"
              :style="{ paddingLeft: `${0.375 + fila.profundidad * 0.9}rem` }"
            >
              <span
                class="h-2 w-2 shrink-0 rounded-full"
                :class="{ 'animate-pulse motion-reduce:animate-none': fila.estado === 'en_curso' }"
                :style="{ backgroundColor: fila.color }"
              />
              <span class="min-w-0 flex-1 truncate text-paper/90">{{ fila.etiqueta }}</span>
              <span
                v-if="fila.modelo"
                class="hidden max-w-[9rem] truncate font-mono text-[10px] text-paper/50 sm:inline"
              >
                {{ fila.modelo }}
              </span>
              <span
                v-if="fila.tokensIn != null || fila.tokensOut != null"
                class="font-mono text-[10px] text-paper/60"
                title="Tokens de entrada → salida"
              >
                {{ formatearNumero(fila.tokensIn) }}→{{ formatearNumero(fila.tokensOut) }}
              </span>
              <span v-if="fila.cached" class="rounded bg-verde/15 px-1 text-[10px] text-verde">caché</span>
              <span v-if="fila.estado === 'error'" class="rounded bg-rojo/15 px-1 text-[10px] text-rojo">error</span>
              <span class="w-16 shrink-0 text-right font-mono text-[11px] text-paper/70 tabular-nums">
                {{ formatearTiempo(fila.dur) }}
              </span>
            </component>

            <div
              v-if="fila.detalle && abiertos[fila.id]"
              class="mt-0.5 mb-1 ml-6 space-y-1 border-l border-paper/10 pl-3 text-[11px] text-paper/60"
            >
              <p v-if="fila.input"><span class="text-paper/40">Entrada:</span> {{ fila.input }}</p>
              <p v-if="fila.output"><span class="text-paper/40">Salida:</span> {{ fila.output }}</p>
              <p v-if="fila.error" class="text-rojo"><span class="text-paper/40">Error:</span> {{ fila.error }}</p>
            </div>
          </li>
        </ol>
      </template>
    </div>
  </section>
</template>
