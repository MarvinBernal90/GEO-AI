<!--
==============================================================================
REQUESTS TABLE (RECORDS)
==============================================================================
File: frontend/src/components/metrics/RequestsTable.vue

One row per measured request, with filters, sortable columns and pagination.
Presentational: the page owns the data (see composables/useMetrics.js). Clicking
a row asks the page to open the detail of that request.
-->
<script setup>
import { computed } from 'vue'

import { STATUS, STATUS_LABEL } from '../../utils/chartTheme.js'
import { formatCost, formatDateTime, formatMs, formatNumber, shortTrace } from '../../utils/format.js'

const props = defineProps({
  page: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
  filters: { type: Object, required: true },
  routes: { type: Array, default: () => [] },
  models: { type: Array, default: () => [] },
  eurPerUsd: { type: Number, default: null },
  pageSize: { type: Number, default: 25 },
})

const emit = defineEmits(['set-filter', 'sort', 'offset', 'select'])

const COLUMNS = [
  { key: 'created_at', label: 'Fecha', sortable: true },
  { key: 'route', label: 'Ruta' },
  { key: 'status', label: 'Estado' },
  { key: 'elapsed_ms', label: 'Duración', sortable: true, right: true },
  { key: 'ttft_ms', label: '1.er token', sortable: true, right: true },
  { key: 'tokens', label: 'Tokens ent. / sal.', right: true },
  { key: 'cost_usd', label: 'Coste', sortable: true, right: true },
  { key: 'llm_model', label: 'Modelo' },
  { key: 'span_count', label: 'Pasos', right: true },
  { key: 'trace_id', label: 'Traza' },
]

const items = computed(() => props.page?.items ?? [])
const total = computed(() => props.page?.total ?? 0)
const from = computed(() => (total.value ? props.filters.offset + 1 : 0))
const to = computed(() => Math.min(props.filters.offset + props.pageSize, total.value))

const ariaSort = (col) =>
  col.sortable && props.filters.sort === col.key
    ? props.filters.direction === 'desc'
      ? 'descending'
      : 'ascending'
    : 'none'
const arrow = (col) => (props.filters.sort === col.key ? (props.filters.direction === 'desc' ? '↓' : '↑') : '')

const inputClass =
  'rounded border border-paper/20 bg-ink px-2 py-1 text-xs text-paper placeholder:text-paper/30 focus:border-brass focus:ring-1 focus:ring-brass focus:outline-none'
</script>

<template>
  <section class="rounded-xl border border-paper/15 bg-ink-light/50 p-5 shadow-lg" aria-labelledby="records-title">
    <header class="mb-3 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 id="records-title" class="text-sm font-semibold text-paper">Registro de peticiones</h2>
        <p class="mt-0.5 text-xs text-paper/60">
          Cada fila es una petición medida. Pulsa una para ver sus pasos. Nunca se guarda el texto del usuario.
        </p>
      </div>

      <div class="flex flex-wrap items-end gap-2">
        <label class="flex flex-col gap-1 text-[10px] tracking-wider text-paper/50 uppercase">
          Estado
          <select
            :class="inputClass"
            :value="filters.status"
            @change="emit('set-filter', 'status', $event.target.value)"
          >
            <option value="">Todos</option>
            <option v-for="(label, key) in STATUS_LABEL" :key="key" :value="key">{{ label }}</option>
          </select>
        </label>
        <label class="flex flex-col gap-1 text-[10px] tracking-wider text-paper/50 uppercase">
          Ruta
          <select :class="inputClass" :value="filters.route" @change="emit('set-filter', 'route', $event.target.value)">
            <option value="">Todas</option>
            <option v-for="r in routes" :key="r" :value="r">{{ r }}</option>
          </select>
        </label>
        <label class="flex flex-col gap-1 text-[10px] tracking-wider text-paper/50 uppercase">
          Modelo
          <select :class="inputClass" :value="filters.model" @change="emit('set-filter', 'model', $event.target.value)">
            <option value="">Todos</option>
            <option v-for="m in models" :key="m" :value="m">{{ m === 'unknown' ? 'Sin modelo' : m }}</option>
          </select>
        </label>
        <label class="flex flex-col gap-1 text-[10px] tracking-wider text-paper/50 uppercase">
          Traza
          <input
            :class="[inputClass, 'w-36 font-mono']"
            type="search"
            maxlength="64"
            placeholder="buscar id…"
            :value="filters.trace_id"
            @input="emit('set-filter', 'trace_id', $event.target.value.trim())"
          />
        </label>
      </div>
    </header>

    <p v-if="error" class="mb-3 rounded border border-rojo/40 bg-rojo/10 px-3 py-2 text-xs text-paper" role="alert">
      No se pudieron cargar los registros: {{ error }}
    </p>

    <div class="overflow-x-auto transition-opacity" :class="{ 'opacity-50': loading }" :aria-busy="loading">
      <table class="w-full min-w-[56rem] text-left text-xs">
        <thead class="text-paper/60">
          <tr class="border-b border-paper/15">
            <th
              v-for="col in COLUMNS"
              :key="col.key"
              scope="col"
              class="px-2 py-2 font-medium whitespace-nowrap"
              :class="col.right ? 'text-right' : ''"
              :aria-sort="ariaSort(col)"
            >
              <button
                v-if="col.sortable"
                type="button"
                class="inline-flex items-center gap-1 rounded hover:text-paper focus:ring-2 focus:ring-brass/50 focus:outline-none"
                @click="emit('sort', col.key)"
              >
                {{ col.label }}<span class="w-3 text-brass" aria-hidden="true">{{ arrow(col) }}</span>
              </button>
              <template v-else>{{ col.label }}</template>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in items"
            :key="row.id"
            class="cursor-pointer border-b border-paper/10 transition-colors hover:bg-paper/5"
            @click="emit('select', row)"
          >
            <td class="px-2 py-2 whitespace-nowrap">
              <button
                type="button"
                class="rounded text-paper/90 hover:text-brass focus:ring-2 focus:ring-brass/50 focus:outline-none"
                @click.stop="emit('select', row)"
              >
                {{ formatDateTime(row.created_at) }}
              </button>
            </td>
            <td class="px-2 py-2 font-mono text-[11px] whitespace-nowrap text-paper/80">{{ row.route }}</td>
            <td class="px-2 py-2 whitespace-nowrap">
              <span class="inline-flex items-center gap-1.5 text-paper/90">
                <span
                  class="h-2 w-2 rounded-full"
                  :style="{ backgroundColor: STATUS[row.status] ?? STATUS.cancelled }"
                />
                {{ STATUS_LABEL[row.status] ?? row.status }}
                <span v-if="row.status_code && row.status_code >= 400" class="text-paper/50"
                  >({{ row.status_code }})</span
                >
              </span>
            </td>
            <td class="px-2 py-2 text-right tabular-nums">{{ formatMs(row.elapsed_ms) }}</td>
            <td class="px-2 py-2 text-right tabular-nums">{{ formatMs(row.ttft_ms) }}</td>
            <td class="px-2 py-2 text-right whitespace-nowrap tabular-nums">
              {{ formatNumber(row.tokens_in) }} / {{ formatNumber(row.tokens_out) }}
            </td>
            <td class="px-2 py-2 text-right tabular-nums" :title="row.cost_usd == null ? 'Sin tarifa configurada' : ''">
              {{ row.cost_usd == null ? 'sin tarifa' : formatCost(row.cost_usd, eurPerUsd) }}
            </td>
            <td class="max-w-[12rem] truncate px-2 py-2 text-paper/80" :title="row.llm_model ?? ''">
              {{ row.llm_model ?? '—' }}
            </td>
            <td class="px-2 py-2 text-right tabular-nums">{{ row.span_count }}</td>
            <td class="px-2 py-2 font-mono text-[11px] whitespace-nowrap text-paper/60" :title="row.trace_id">
              {{ shortTrace(row.trace_id) }}
            </td>
          </tr>
          <tr v-if="!items.length">
            <td :colspan="COLUMNS.length" class="px-2 py-10 text-center text-sm text-paper/50">
              {{ loading ? 'Cargando…' : 'No hay peticiones con estos filtros.' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer class="mt-3 flex items-center justify-between text-xs text-paper/60">
      <span class="tabular-nums">{{ from }}–{{ to }} de {{ formatNumber(total) }}</span>
      <div class="flex gap-2">
        <button
          type="button"
          class="rounded border border-paper/20 px-3 py-1 transition hover:border-brass hover:text-brass focus:ring-2 focus:ring-brass/50 focus:outline-none disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:border-paper/20 disabled:hover:text-paper/60"
          :disabled="filters.offset === 0"
          @click="emit('offset', filters.offset - pageSize)"
        >
          ← Anterior
        </button>
        <button
          type="button"
          class="rounded border border-paper/20 px-3 py-1 transition hover:border-brass hover:text-brass focus:ring-2 focus:ring-brass/50 focus:outline-none disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:border-paper/20 disabled:hover:text-paper/60"
          :disabled="filters.offset + pageSize >= total"
          @click="emit('offset', filters.offset + pageSize)"
        >
          Siguiente →
        </button>
      </div>
    </footer>
  </section>
</template>
