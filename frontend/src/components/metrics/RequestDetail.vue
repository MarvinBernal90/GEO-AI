<!--
==============================================================================
REQUEST DETAIL (DRAWER)
==============================================================================
File: frontend/src/components/metrics/RequestDetail.vue

Opens one request: its totals and a waterfall of every step (span), one lane per
row indented by parent, colored by actor, on a shared time axis. A row with extra
information (summaries, error class) expands on click.

Only sizes, counts and exception class names are stored by the backend, so there
is no user text to show here.
-->
<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { getMetricsRequest } from '../../services/api.js'
import { STATUS, STATUS_LABEL, actorInfo } from '../../utils/chartTheme.js'
import { formatCost, formatDateTime, formatMs, formatNumber } from '../../utils/format.js'

const props = defineProps({
  requestId: { type: Number, default: null },
  eurPerUsd: { type: Number, default: null },
})
const emit = defineEmits(['close'])

const detail = ref(null)
const loading = ref(false)
const error = ref(null)
const expanded = ref({})
const closeButton = ref(null)
let seq = 0

watch(
  () => props.requestId,
  async (id) => {
    const mine = ++seq
    detail.value = null
    error.value = null
    expanded.value = {}
    if (id == null) return
    loading.value = true
    await nextTick()
    closeButton.value?.focus()
    try {
      const data = await getMetricsRequest(id)
      if (mine === seq) detail.value = data
    } catch (e) {
      if (mine === seq) error.value = e.message
    } finally {
      if (mine === seq) loading.value = false
    }
  },
  { immediate: true },
)

const onKey = (e) => {
  if (e.key === 'Escape' && props.requestId != null) emit('close')
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))

// ---- Waterfall: depth by parent chain, positions as % of the whole request.
const rows = computed(() => {
  const spans = detail.value?.spans ?? []
  const byId = new Map(spans.map((s) => [s.span_id, s]))
  const depthOf = (s) => {
    let depth = 0
    let current = s
    // The chain is bounded so a corrupt parent loop cannot hang the page.
    while (current.parent_id != null && byId.has(current.parent_id) && depth < 20) {
      current = byId.get(current.parent_id)
      depth += 1
    }
    return depth
  }
  const end = Math.max(1, ...spans.map((s) => s.offset_ms + (s.duration_ms ?? 0)))
  return spans.map((s) => {
    const left = (s.offset_ms / end) * 100
    const width = Math.min(Math.max(((s.duration_ms ?? 0) / end) * 100, 0.7), 100 - left)
    const extra = Boolean(s.input_summary || s.output_summary || s.error || s.model)
    return { ...s, depth: depthOf(s), left, width, extra, actor_info: actorInfo(s.actor) }
  })
})

const axisTotal = computed(() => {
  const spans = detail.value?.spans ?? []
  return Math.max(0, ...spans.map((s) => s.offset_ms + (s.duration_ms ?? 0)))
})
const ticks = computed(() => [0, 0.25, 0.5, 0.75, 1].map((f) => formatMs(axisTotal.value * f)))

const actorsPresent = computed(() =>
  [...new Set(rows.value.map((r) => r.actor))].map((a) => ({ key: a, ...actorInfo(a) })),
)

const summary = computed(() => {
  const d = detail.value
  if (!d) return []
  return [
    { label: 'Duración', value: formatMs(d.elapsed_ms) },
    { label: '1.er token', value: formatMs(d.ttft_ms) },
    { label: 'Tokens entrada', value: formatNumber(d.tokens_in) },
    { label: 'Tokens salida', value: formatNumber(d.tokens_out) },
    { label: 'Tokens de razonamiento', value: formatNumber(d.thought_tokens) },
    { label: 'Coste', value: d.cost_usd == null ? 'sin tarifa' : formatCost(d.cost_usd, props.eurPerUsd) },
    { label: 'Modelo', value: d.llm_model ?? '—' },
    { label: 'Embeddings', value: d.embedding_model ?? '—' },
  ]
})

const toggle = (id) => (expanded.value = { ...expanded.value, [id]: !expanded.value[id] })
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition-opacity duration-300"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="requestId != null" class="fixed inset-0 z-[1999] bg-ink/70 backdrop-blur-sm" @click="emit('close')" />
    </Transition>

    <Transition
      enter-active-class="transition-transform duration-300 ease-out"
      enter-from-class="translate-x-full"
      enter-to-class="translate-x-0"
      leave-active-class="transition-transform duration-200 ease-in"
      leave-from-class="translate-x-0"
      leave-to-class="translate-x-full"
    >
      <aside
        v-if="requestId != null"
        class="fixed inset-y-0 right-0 z-[2000] flex w-full max-w-3xl flex-col overflow-y-auto border-l border-paper/15 bg-ink text-paper shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="request-detail-title"
      >
        <header
          class="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-paper/10 bg-ink/95 px-6 py-4 backdrop-blur"
        >
          <div class="min-w-0">
            <p class="font-mono text-[11px] tracking-widest text-paper/50 uppercase">Detalle de la petición</p>
            <h2 id="request-detail-title" class="truncate font-mono text-sm text-paper" :title="detail?.trace_id">
              {{ detail?.trace_id ?? '…' }}
            </h2>
            <p v-if="detail" class="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-paper/60">
              <span>{{ formatDateTime(detail.created_at) }}</span>
              <span class="font-mono">{{ detail.route }}</span>
              <span class="inline-flex items-center gap-1.5 text-paper/90">
                <span
                  class="h-2 w-2 rounded-full"
                  :style="{ backgroundColor: STATUS[detail.status] ?? STATUS.cancelled }"
                />
                {{ STATUS_LABEL[detail.status] ?? detail.status }}
                <span v-if="detail.status_code">({{ detail.status_code }})</span>
              </span>
            </p>
          </div>
          <button
            ref="closeButton"
            type="button"
            class="rounded-full px-3 py-1.5 text-lg text-paper/50 transition-colors hover:bg-paper/10 hover:text-paper focus:ring-2 focus:ring-brass/50 focus:outline-none"
            aria-label="Cerrar detalle"
            @click="emit('close')"
          >
            ✕
          </button>
        </header>

        <div class="space-y-6 px-6 py-5">
          <p v-if="loading" class="py-10 text-center text-sm text-paper/60">Cargando…</p>
          <p v-else-if="error" class="rounded border border-rojo/40 bg-rojo/10 px-3 py-2 text-sm" role="alert">
            {{ error }}
          </p>

          <template v-else-if="detail">
            <dl class="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div
                v-for="item in summary"
                :key="item.label"
                class="min-w-0 rounded-lg border border-paper/10 bg-ink-light/50 p-3"
              >
                <dt class="truncate text-[11px] text-paper/50">{{ item.label }}</dt>
                <dd class="mt-1 truncate text-sm font-semibold" :title="item.value">{{ item.value }}</dd>
              </div>
            </dl>

            <p v-if="detail.dropped_spans" class="rounded border border-ambar/40 bg-ambar/10 px-3 py-2 text-xs">
              Atención: se descartaron {{ detail.dropped_spans }} pasos por exceder el límite, así que la lista está
              incompleta.
            </p>

            <section aria-labelledby="waterfall-title">
              <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
                <h3 id="waterfall-title" class="text-sm font-semibold">Pasos de la petición ({{ rows.length }})</h3>
                <ul class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-paper/70" aria-label="Leyenda de actores">
                  <li v-for="a in actorsPresent" :key="a.key" class="flex items-center gap-1.5">
                    <span class="h-[3px] w-3.5 rounded-sm" :style="{ backgroundColor: a.color }" />{{ a.label }}
                  </li>
                </ul>
              </div>

              <p v-if="!rows.length" class="py-6 text-center text-sm text-paper/50">Esta petición no registró pasos.</p>

              <ol v-else class="space-y-0.5">
                <li v-for="row in rows" :key="row.span_id">
                  <component
                    :is="row.extra ? 'button' : 'div'"
                    v-bind="
                      row.extra
                        ? {
                            type: 'button',
                            'aria-expanded': Boolean(expanded[row.span_id]),
                            onClick: () => toggle(row.span_id),
                          }
                        : {}
                    "
                    class="grid w-full grid-cols-[minmax(8rem,14rem)_1fr_4.5rem] items-center gap-3 rounded px-1.5 py-1 text-left text-xs hover:bg-paper/5 focus:ring-2 focus:ring-brass/50 focus:outline-none"
                  >
                    <span
                      class="truncate text-paper/90"
                      :style="{ paddingLeft: `${row.depth * 0.9}rem` }"
                      :title="row.name"
                    >
                      {{ row.name }}
                      <span v-if="row.cached" class="ml-1 rounded bg-paper/10 px-1 text-[10px] text-paper/70"
                        >caché</span
                      >
                      <span v-if="row.status === 'error'" class="ml-1 rounded bg-rojo/20 px-1 text-[10px] text-paper"
                        >error</span
                      >
                    </span>
                    <span class="relative h-4 rounded bg-paper/5">
                      <span
                        class="absolute top-[6px] h-[4px] rounded-sm"
                        :style="{ left: `${row.left}%`, width: `${row.width}%`, backgroundColor: row.actor_info.color }"
                      />
                    </span>
                    <span class="text-right tabular-nums text-paper/70">{{ formatMs(row.duration_ms) }}</span>
                  </component>

                  <dl
                    v-if="row.extra && expanded[row.span_id]"
                    class="mt-0.5 mb-1.5 ml-6 space-y-1 border-l border-paper/10 pl-3 text-[11px] text-paper/70"
                  >
                    <div v-if="row.model">
                      <dt class="inline text-paper/40">Modelo:</dt>
                      <dd class="inline">{{ row.model }}</dd>
                    </div>
                    <div v-if="row.tokens_in != null || row.tokens_out != null">
                      <dt class="inline text-paper/40">Tokens:</dt>
                      <dd class="inline tabular-nums">
                        {{ formatNumber(row.tokens_in) }} → {{ formatNumber(row.tokens_out) }}
                      </dd>
                    </div>
                    <div v-if="row.ttft_ms != null">
                      <dt class="inline text-paper/40">1.er token:</dt>
                      <dd class="inline">{{ formatMs(row.ttft_ms) }}</dd>
                    </div>
                    <div v-if="row.input_summary">
                      <dt class="inline text-paper/40">Entrada:</dt>
                      <dd class="inline">{{ row.input_summary }}</dd>
                    </div>
                    <div v-if="row.output_summary">
                      <dt class="inline text-paper/40">Salida:</dt>
                      <dd class="inline">{{ row.output_summary }}</dd>
                    </div>
                    <div v-if="row.error">
                      <dt class="inline text-paper/40">Error:</dt>
                      <dd class="inline font-mono">{{ row.error }}</dd>
                    </div>
                  </dl>
                </li>
              </ol>

              <div
                v-if="rows.length"
                class="mt-1 grid grid-cols-[minmax(8rem,14rem)_1fr_4.5rem] gap-3 px-1.5 text-[10px] text-paper/40"
              >
                <span />
                <span class="flex justify-between"
                  ><span v-for="(t, i) in ticks" :key="i">{{ t }}</span></span
                >
                <span />
              </div>
            </section>
          </template>
        </div>
      </aside>
    </Transition>
  </Teleport>
</template>
