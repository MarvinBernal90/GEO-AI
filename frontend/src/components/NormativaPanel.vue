<!--
==============================================================================
LEGAL PANEL (NORMATIVA COLUMN)
==============================================================================
File: frontend/src/components/NormativaPanel.vue

Dark side panel with the legal side of the last report:
- the legal basis written by the RAG,
- the list of cited articles; clicking one opens its full text
  (RegulationsViewer) inside this same panel.
Presentational: the open/closed state and the selected article live in App.vue.
-->
<script setup>
import { computed } from 'vue'

import RegulationsViewer from './RegulationsViewer.vue'

const props = defineProps({
  report: { type: Object, default: null },
  articulo: { type: Object, default: null },
})

const emit = defineEmits(['cerrar', 'seleccionar'])

const articulos = computed(() => props.report?.articulos ?? [])
const fundamento = computed(() => props.report?.respuestaLegal ?? '')
const distrito = computed(() => props.report?.datos?.nom_districte ?? '')
</script>

<template>
  <section class="flex h-full min-h-0 flex-col bg-ink-light text-paper" aria-label="Normativa aplicable">
    <header class="flex items-start justify-between gap-3 border-b border-paper/10 px-4 py-3">
      <div class="min-w-0">
        <p class="font-mono text-[10px] tracking-widest text-paper/50 uppercase">Normativa aplicable</p>
        <h2 v-if="distrito" class="truncate font-display text-base font-semibold text-paper">{{ distrito }}</h2>
      </div>
      <button
        type="button"
        class="rounded-full px-2.5 py-1 text-base text-paper/50 transition-colors hover:bg-paper/10 hover:text-paper focus-visible:ring-2 focus-visible:ring-brass focus-visible:outline-none"
        aria-label="Cerrar normativa"
        @click="emit('cerrar')"
      >
        ✕
      </button>
    </header>

    <div class="min-h-0 flex-1 overflow-y-auto">
      <!-- Full text of one article -->
      <RegulationsViewer v-if="articulo" :articulo="articulo" @cerrar="emit('seleccionar', null)" />

      <!-- Overview: legal basis + cited articles -->
      <div v-else class="space-y-6 px-4 py-4">
        <div v-if="fundamento">
          <h3 class="mb-2 font-mono text-[10px] font-semibold tracking-widest text-brass uppercase">
            Fundamento legal
          </h3>
          <p class="text-sm leading-relaxed whitespace-pre-line text-paper/85">{{ fundamento }}</p>
        </div>

        <div v-if="articulos.length">
          <h3 class="mb-2 font-mono text-[10px] font-semibold tracking-widest text-brass uppercase">
            Artículos citados
          </h3>
          <ul class="space-y-2">
            <li v-for="item in articulos" :key="`${item.fuente_legal}-${item.numero_articulo}`">
              <button
                type="button"
                class="w-full rounded-lg border border-paper/10 bg-ink px-3 py-2.5 text-left transition hover:border-brass/50 focus-visible:ring-2 focus-visible:ring-brass focus-visible:outline-none"
                @click="emit('seleccionar', item)"
              >
                <span class="block font-mono text-xs text-brass">Art. {{ item.numero_articulo }}</span>
                <span class="mt-0.5 block text-xs text-paper/60">{{ item.fuente_legal }}</span>
              </button>
            </li>
          </ul>
        </div>

        <p v-if="!fundamento && !articulos.length" class="text-sm text-paper/60">
          Este informe no tiene normativa asociada.
        </p>
      </div>
    </div>
  </section>
</template>
