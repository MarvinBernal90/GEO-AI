<!--
==============================================================================
CHART CARD
==============================================================================
File: frontend/src/components/metrics/ChartCard.vue

Panel that frames one chart: title, one-line subtitle, an optional "Tabla"
toggle and an empty state. Every chart passes its numbers in `table`, so the
values are reachable without hovering and without seeing colors.
-->
<script setup>
import { ref } from 'vue'

defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  empty: { type: Boolean, default: false },
  emptyText: { type: String, default: 'Sin datos en este periodo.' },
  // { columns: [{ key, label, align? }], rows: [{ [key]: string|number }] }
  table: { type: Object, default: null },
})

const showTable = ref(false)
</script>

<template>
  <section class="flex min-w-0 flex-col rounded-xl border border-paper/15 bg-ink-light/50 p-5 shadow-lg">
    <header class="mb-3 flex items-start justify-between gap-3">
      <div class="min-w-0">
        <h3 class="text-sm font-semibold text-paper">{{ title }}</h3>
        <p v-if="subtitle" class="mt-0.5 text-xs text-paper/60">{{ subtitle }}</p>
      </div>
      <button
        v-if="table && !empty"
        type="button"
        class="shrink-0 rounded border border-paper/20 px-2 py-0.5 font-mono text-[10px] tracking-wider text-paper/70 uppercase transition hover:border-brass hover:text-brass focus:ring-2 focus:ring-brass/50 focus:outline-none"
        :aria-pressed="showTable"
        @click="showTable = !showTable"
      >
        {{ showTable ? 'Gráfico' : 'Tabla' }}
      </button>
    </header>

    <p v-if="empty" class="flex min-h-[8rem] flex-1 items-center justify-center text-center text-sm text-paper/50">
      {{ emptyText }}
    </p>

    <div v-else-if="showTable && table" class="max-h-[22rem] overflow-auto">
      <table class="w-full text-left text-xs">
        <thead class="sticky top-0 bg-ink-light text-paper/60">
          <tr>
            <th
              v-for="col in table.columns"
              :key="col.key"
              scope="col"
              class="px-2 py-1.5 font-medium"
              :class="col.align === 'right' ? 'text-right' : ''"
            >
              {{ col.label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in table.rows" :key="i" class="border-t border-paper/10">
            <td
              v-for="col in table.columns"
              :key="col.key"
              class="px-2 py-1.5 text-paper/90"
              :class="col.align === 'right' ? 'text-right tabular-nums' : ''"
            >
              {{ row[col.key] }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <slot v-else />
  </section>
</template>
