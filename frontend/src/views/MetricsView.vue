<!--
==============================================================================
METRICS DASHBOARD (ROUTE "/metrics")
==============================================================================
File: frontend/src/views/MetricsView.vue

Reads the request metrics saved by the backend (GET /api/metrics/*) and shows:
  - KPI tiles: volume, errors, latency, first token, tokens, cost
  - charts: traffic, latency over time, latency distribution, tokens, cost,
    time by actor, slowest steps, most frequent errors
  - health meters: request status and cache hit rate
  - tables by route and by model
  - the record of every request, with a drawer that opens its steps

One time range (first row) scopes everything below it. Every chart has a "Tabla"
twin with the same numbers. The data comes from useMetrics().
-->
<script setup>
import { computed, ref } from 'vue'

import ChartCard from '../components/metrics/ChartCard.vue'
import EChart from '../components/metrics/EChart.vue'
import KpiCard from '../components/metrics/KpiCard.vue'
import RequestDetail from '../components/metrics/RequestDetail.vue'
import RequestsTable from '../components/metrics/RequestsTable.vue'
import { PAGE_SIZE, RANGES, useMetrics } from '../composables/useMetrics.js'
import {
  BAR_MAX_WIDTH,
  BAR_RADIUS_RIGHT,
  BAR_RADIUS_UP,
  COLORS,
  INK,
  SERIES,
  STATUS,
  STATUS_LABEL,
  actorInfo,
  baseOption,
  categoryAxis,
  tooltipHtml,
  valueAxis,
} from '../utils/chartTheme.js'
import {
  formatBucket,
  formatCompact,
  formatCost,
  formatDateTime,
  formatMs,
  formatNumber,
  formatPercent,
} from '../utils/format.js'

const {
  range,
  overview,
  overviewLoading,
  overviewError,
  filters,
  page,
  pageLoading,
  pageError,
  autoRefresh,
  lastUpdated,
  refresh,
  setRange,
  setFilter,
  setSort,
  goToOffset,
} = useMetrics()

const selectedId = ref(null)

const kpis = computed(() => overview.value?.kpis ?? null)
const series = computed(() => overview.value?.timeseries ?? [])
const bucket = computed(() => overview.value?.bucket ?? 'hour')
const rate = computed(() => overview.value?.eur_per_usd ?? null)
const hasData = computed(() => (kpis.value?.requests ?? 0) > 0)
const labels = computed(() => series.value.map((b) => formatBucket(b.t, bucket.value)))
const bucketWord = computed(() => (bucket.value === 'hour' ? 'hora' : 'día'))

// The newest bucket is still filling up when it contains "now"; the tooltip says so.
const partialIndex = computed(() => {
  const last = series.value.length - 1
  if (last < 0 || !overview.value) return -1
  const step = bucket.value === 'hour' ? 3_600_000 : 86_400_000
  return new Date(series.value[last].t).getTime() + step > new Date(overview.value.until).getTime() ? last : -1
})

const routeOptions = computed(() => (overview.value?.by_route ?? []).map((r) => r.route))
const modelOptions = computed(() => (overview.value?.by_model ?? []).map((m) => m.model))

const costFmt = (usd) => formatCost(usd, rate.value)
/** A group with no priced request has an unknown cost, which must not read as 0. */
const groupCost = (g) => (g.priced_requests ? costFmt(g.cost_usd) : g.tokens_in + g.tokens_out > 0 ? 'sin tarifa' : '—')

// ---------------------------------------------------------------------------
// KPI TILES
// ---------------------------------------------------------------------------
const tiles = computed(() => {
  const k = kpis.value
  if (!k) return []
  const ts = series.value
  const errorTone = !k.requests ? 'default' : k.errors ? 'critical' : 'good'
  const unpriced = k.unpriced_requests ? ` · ${formatNumber(k.unpriced_requests)} sin tarifa (no sumadas)` : ''
  return [
    {
      key: 'requests',
      label: 'Peticiones',
      value: formatNumber(k.requests),
      hint: `${formatNumber(k.ok)} correctas · ${formatNumber(k.cancelled)} canceladas`,
      trend: ts.map((b) => b.requests),
      color: COLORS.requests,
    },
    {
      key: 'errors',
      label: 'Tasa de error',
      value: formatPercent(k.error_rate),
      hint: k.requests ? `${formatNumber(k.errors)} con error` : 'Sin peticiones',
      tone: errorTone,
      trend: ts.map((b) => b.errors),
      color: STATUS.error,
    },
    {
      key: 'latency',
      label: 'Latencia mediana',
      value: formatMs(k.latency_ms.p50),
      hint: `p95 ${formatMs(k.latency_ms.p95)} · máx. ${formatMs(k.latency_ms.max)}`,
      trend: ts.map((b) => b.avg_ms).filter((v) => v != null),
      color: COLORS.latencyAvg,
    },
    {
      key: 'ttft',
      label: 'Primer token (mediana)',
      value: formatMs(k.ttft_ms.p50),
      hint: `p95 ${formatMs(k.ttft_ms.p95)} · media ${formatMs(k.ttft_ms.avg)}`,
    },
    {
      key: 'tokens',
      label: 'Tokens entrada / salida',
      value: `${formatCompact(k.tokens_in)} / ${formatCompact(k.tokens_out)}`,
      hint: k.thought_tokens ? `+ ${formatCompact(k.thought_tokens)} de razonamiento` : 'Sin tokens de razonamiento',
      trend: ts.map((b) => b.tokens_out),
      color: COLORS.tokensOut,
    },
    {
      key: 'cost',
      label: rate.value ? 'Coste (EUR)' : 'Coste (USD)',
      value: costFmt(k.cost_usd),
      hint:
        (k.avg_cost_usd == null ? 'Sin peticiones con tarifa' : `Media ${costFmt(k.avg_cost_usd)} / petición`) +
        unpriced,
      trend: ts.map((b) => b.cost_usd),
      color: COLORS.cost,
    },
  ]
})

// ---------------------------------------------------------------------------
// CHART OPTIONS
// ---------------------------------------------------------------------------
/** Tooltip for charts with a shared axis: one row per series, value first. */
function axisTooltip(formats, partialAt = -1) {
  return (params) => {
    const list = Array.isArray(params) ? params : [params]
    const rows = list
      .filter((p) => p.value != null && p.value !== '-')
      .map((p) => ({ color: p.color, name: p.seriesName, value: (formats[p.seriesName] ?? formatNumber)(p.value) }))
    const partial = list[0]?.dataIndex === partialAt ? ' (en curso)' : ''
    return tooltipHtml(`${list[0]?.axisValueLabel ?? ''}${partial}`, rows)
  }
}

const line = (name, data, color, area = false) => ({
  name,
  type: 'line',
  data,
  showSymbol: data.length < 3,
  symbol: 'circle',
  symbolSize: 8,
  lineStyle: { width: 2, color, cap: 'round', join: 'round' },
  itemStyle: { color, borderColor: INK.surface, borderWidth: 2 },
  areaStyle: area ? { color, opacity: 0.1 } : undefined,
})

function timeOption({ list, yFormat, formats, legend = true }) {
  const base = baseOption({ legend })
  return {
    ...base,
    xAxis: categoryAxis(labels.value, { boundaryGap: false }),
    yAxis: valueAxis(yFormat, { min: 0 }),
    tooltip: {
      ...base.tooltip,
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: INK.axis } },
      formatter: axisTooltip(formats, partialIndex.value),
    },
    series: list,
  }
}

const trafficOption = computed(() =>
  timeOption({
    list: [
      line(
        'Peticiones',
        series.value.map((b) => b.requests),
        COLORS.requests,
        true,
      ),
      line(
        'Con error',
        series.value.map((b) => b.errors),
        STATUS.error,
      ),
    ],
    yFormat: formatCompact,
    formats: { Peticiones: formatNumber, 'Con error': formatNumber },
  }),
)

const latencyOption = computed(() =>
  timeOption({
    list: [
      line(
        'Media',
        series.value.map((b) => b.avg_ms),
        COLORS.latencyAvg,
      ),
      line(
        'p95',
        series.value.map((b) => b.p95_ms),
        COLORS.latencyP95,
      ),
    ],
    yFormat: formatMs,
    formats: { Media: formatMs, p95: formatMs },
  }),
)

const costOption = computed(() =>
  timeOption({
    list: [
      line(
        rate.value ? 'Coste (EUR)' : 'Coste (USD)',
        series.value.map((b) => b.cost_usd),
        COLORS.cost,
        true,
      ),
    ],
    yFormat: (v) => costFmt(v),
    formats: { 'Coste (EUR)': costFmt, 'Coste (USD)': costFmt },
    legend: false,
  }),
)

const stackedBar = (name, data, color, radius) => ({
  name,
  type: 'bar',
  stack: 'tokens',
  data,
  barMaxWidth: BAR_MAX_WIDTH,
  // A 2 px surface-colored edge is the gap between touching fills.
  itemStyle: { color, borderColor: INK.surface, borderWidth: 2, borderRadius: radius },
})

const tokensOption = computed(() => {
  const base = baseOption({ legend: true })
  return {
    ...base,
    xAxis: categoryAxis(labels.value),
    yAxis: valueAxis(formatCompact),
    tooltip: {
      ...base.tooltip,
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(245, 241, 232, 0.05)' } },
      formatter: axisTooltip({ Entrada: formatNumber, Salida: formatNumber }, partialIndex.value),
    },
    series: [
      stackedBar(
        'Entrada',
        series.value.map((b) => b.tokens_in),
        COLORS.tokensIn,
        0,
      ),
      stackedBar(
        'Salida',
        series.value.map((b) => b.tokens_out),
        COLORS.tokensOut,
        BAR_RADIUS_UP,
      ),
    ],
  }
})

const histogramOption = computed(() => {
  const bins = overview.value?.latency_histogram ?? []
  const base = baseOption()
  return {
    ...base,
    xAxis: categoryAxis(bins.map((b) => b.label)),
    yAxis: valueAxis(formatCompact, { minInterval: 1 }),
    tooltip: {
      ...base.tooltip,
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(245, 241, 232, 0.05)' } },
      formatter: axisTooltip({ Peticiones: formatNumber }),
    },
    series: [
      {
        name: 'Peticiones',
        type: 'bar',
        data: bins.map((b) => b.requests),
        barMaxWidth: BAR_MAX_WIDTH,
        itemStyle: { color: SERIES[0], borderRadius: BAR_RADIUS_UP },
      },
    ],
  }
})

/** Horizontal bars, one color (a single series), value at the tip. Biggest on top. */
function hbarOption({ names, values, seriesName, format, tooltipExtra }) {
  const base = baseOption()
  return {
    ...base,
    grid: { left: 8, right: 64, top: 8, bottom: 4, containLabel: true },
    xAxis: valueAxis(format, { min: 0 }),
    yAxis: {
      type: 'category',
      inverse: true,
      data: names,
      axisLine: { lineStyle: { color: INK.axis } },
      axisTick: { show: false },
      axisLabel: { color: INK.secondary, fontSize: 11, width: 130, overflow: 'truncate' },
    },
    tooltip: {
      ...base.tooltip,
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(245, 241, 232, 0.05)' } },
      formatter: (params) => {
        const p = Array.isArray(params) ? params[0] : params
        return tooltipHtml(p.name, [
          { color: SERIES[0], name: seriesName, value: format(p.value) },
          ...(tooltipExtra?.(p.dataIndex) ?? []),
        ])
      },
    },
    series: [
      {
        name: seriesName,
        type: 'bar',
        data: values,
        barMaxWidth: BAR_MAX_WIDTH,
        itemStyle: { color: SERIES[0], borderRadius: BAR_RADIUS_RIGHT },
        label: { show: true, position: 'right', color: INK.secondary, fontSize: 11, formatter: (p) => format(p.value) },
      },
    ],
  }
}

const actors = computed(() => overview.value?.by_actor ?? [])
const actorOption = computed(() =>
  hbarOption({
    names: actors.value.map((a) => actorInfo(a.actor).label),
    values: actors.value.map((a) => a.avg_ms ?? 0),
    seriesName: 'Duración media',
    format: formatMs,
    tooltipExtra: (i) => [
      { name: 'llamadas', value: formatNumber(actors.value[i].calls) },
      { name: 'con error', value: formatNumber(actors.value[i].errors) },
    ],
  }),
)

const spans = computed(() => overview.value?.top_spans ?? [])
const spansOption = computed(() =>
  hbarOption({
    names: spans.value.map((s) => s.name),
    values: spans.value.map((s) => s.total_ms),
    seriesName: 'Tiempo acumulado',
    format: formatMs,
    tooltipExtra: (i) => [
      { name: 'llamadas', value: formatNumber(spans.value[i].calls) },
      { name: 'media', value: formatMs(spans.value[i].avg_ms) },
      { name: 'máximo', value: formatMs(spans.value[i].max_ms) },
    ],
  }),
)

const errors = computed(() => overview.value?.top_errors ?? [])
const errorsOption = computed(() =>
  hbarOption({
    names: errors.value.map((e) => e.error),
    values: errors.value.map((e) => e.count),
    seriesName: 'Ocurrencias',
    format: formatNumber,
  }),
)

// ---------------------------------------------------------------------------
// TABLE TWINS (same numbers as the charts)
// ---------------------------------------------------------------------------
const trafficTable = computed(() => ({
  columns: [
    { key: 't', label: bucketWord.value === 'hora' ? 'Hora' : 'Día' },
    { key: 'requests', label: 'Peticiones', align: 'right' },
    { key: 'errors', label: 'Con error', align: 'right' },
  ],
  rows: series.value.map((b, i) => ({
    t: labels.value[i],
    requests: formatNumber(b.requests),
    errors: formatNumber(b.errors),
  })),
}))
const latencyTable = computed(() => ({
  columns: [
    { key: 't', label: 'Periodo' },
    { key: 'avg', label: 'Media', align: 'right' },
    { key: 'p95', label: 'p95', align: 'right' },
  ],
  rows: series.value.map((b, i) => ({ t: labels.value[i], avg: formatMs(b.avg_ms), p95: formatMs(b.p95_ms) })),
}))
const tokensTable = computed(() => ({
  columns: [
    { key: 't', label: 'Periodo' },
    { key: 'in', label: 'Entrada', align: 'right' },
    { key: 'out', label: 'Salida', align: 'right' },
  ],
  rows: series.value.map((b, i) => ({
    t: labels.value[i],
    in: formatNumber(b.tokens_in),
    out: formatNumber(b.tokens_out),
  })),
}))
const costTable = computed(() => ({
  columns: [
    { key: 't', label: 'Periodo' },
    { key: 'cost', label: rate.value ? 'Coste (EUR)' : 'Coste (USD)', align: 'right' },
  ],
  rows: series.value.map((b, i) => ({ t: labels.value[i], cost: costFmt(b.cost_usd) })),
}))
const histogramTable = computed(() => ({
  columns: [
    { key: 'label', label: 'Duración' },
    { key: 'requests', label: 'Peticiones', align: 'right' },
  ],
  rows: (overview.value?.latency_histogram ?? []).map((b) => ({ label: b.label, requests: formatNumber(b.requests) })),
}))
const actorTable = computed(() => ({
  columns: [
    { key: 'actor', label: 'Actor' },
    { key: 'calls', label: 'Llamadas', align: 'right' },
    { key: 'errors', label: 'Errores', align: 'right' },
    { key: 'avg', label: 'Media', align: 'right' },
  ],
  rows: actors.value.map((a) => ({
    actor: actorInfo(a.actor).label,
    calls: formatNumber(a.calls),
    errors: formatNumber(a.errors),
    avg: formatMs(a.avg_ms),
  })),
}))
const spansTable = computed(() => ({
  columns: [
    { key: 'name', label: 'Paso' },
    { key: 'calls', label: 'Llamadas', align: 'right' },
    { key: 'avg', label: 'Media', align: 'right' },
    { key: 'max', label: 'Máx.', align: 'right' },
    { key: 'total', label: 'Total', align: 'right' },
  ],
  rows: spans.value.map((s) => ({
    name: s.name,
    calls: formatNumber(s.calls),
    avg: formatMs(s.avg_ms),
    max: formatMs(s.max_ms),
    total: formatMs(s.total_ms),
  })),
}))
const errorsTable = computed(() => ({
  columns: [
    { key: 'error', label: 'Excepción' },
    { key: 'count', label: 'Ocurrencias', align: 'right' },
  ],
  rows: errors.value.map((e) => ({ error: e.error, count: formatNumber(e.count) })),
}))

// ---------------------------------------------------------------------------
// HEALTH METERS
// ---------------------------------------------------------------------------
const statusBar = computed(() => {
  const total = kpis.value?.requests ?? 0
  return (overview.value?.by_status ?? []).map((s) => ({
    key: s.status,
    label: STATUS_LABEL[s.status] ?? s.status,
    count: s.requests,
    share: total ? (s.requests / total) * 100 : 0,
    color: STATUS[s.status] ?? STATUS.cancelled,
  }))
})
const cache = computed(() => overview.value?.cache ?? { hits: 0, total: 0 })
const cacheRate = computed(() => (cache.value.total ? cache.value.hits / cache.value.total : null))

const rangeLabel = computed(() => RANGES.find((r) => r.value === range.value)?.label ?? '')
const dimmed = computed(() => overviewLoading.value && overview.value)
</script>

<template>
  <main class="fondo-plano min-h-screen">
    <div class="mx-auto max-w-[1600px] space-y-6 px-4 py-8 sm:px-6 lg:px-8">
      <!-- Header -->
      <header class="flex flex-wrap items-end justify-between gap-4">
        <div>
          <RouterLink
            to="/"
            class="mb-2 inline-block rounded font-mono text-xs font-bold tracking-[0.2em] text-brass uppercase hover:underline focus:ring-2 focus:ring-brass/50 focus:outline-none"
          >
            ← Geo-Yield-AI
          </RouterLink>
          <h1 class="font-display text-3xl font-semibold text-paper sm:text-4xl">Métricas de las peticiones</h1>
          <p class="mt-2 max-w-2xl text-sm leading-relaxed text-paper/70">
            Tiempo, tokens y coste de cada consulta al asistente y a los informes. Solo se guardan tamaños, recuentos y
            nombres de modelo, nunca lo que escribe el usuario.
          </p>
        </div>

        <div class="flex flex-wrap items-center gap-3 text-xs text-paper/60">
          <span v-if="lastUpdated" class="tabular-nums">Actualizado {{ formatDateTime(lastUpdated) }}</span>
          <label class="flex cursor-pointer items-center gap-2">
            <input v-model="autoRefresh" type="checkbox" class="accent-brass" />
            Cada 30 s
          </label>
          <button
            type="button"
            class="rounded border border-paper/20 px-3 py-1.5 text-paper/80 transition hover:border-brass hover:text-brass focus:ring-2 focus:ring-brass/50 focus:outline-none disabled:opacity-40"
            :disabled="overviewLoading"
            @click="refresh"
          >
            {{ overviewLoading ? 'Actualizando…' : 'Actualizar' }}
          </button>
        </div>
      </header>

      <!-- Filter row: the range scopes everything below -->
      <div class="flex flex-wrap items-center gap-3" role="group" aria-label="Periodo">
        <span class="text-xs tracking-wider text-paper/50 uppercase">Periodo</span>
        <div class="inline-flex overflow-hidden rounded-lg border border-paper/20">
          <button
            v-for="r in RANGES"
            :key="r.value"
            type="button"
            class="px-3.5 py-1.5 text-xs transition focus:ring-2 focus:ring-brass/50 focus:outline-none focus-visible:ring-inset"
            :class="
              range === r.value ? 'bg-brass text-ink font-semibold' : 'text-paper/70 hover:bg-paper/10 hover:text-paper'
            "
            :aria-pressed="range === r.value"
            @click="setRange(r.value)"
          >
            {{ r.label }}
          </button>
        </div>
      </div>

      <!-- Notices -->
      <p v-if="overviewError" class="rounded-lg border border-rojo/40 bg-rojo/10 px-4 py-3 text-sm" role="alert">
        No se pudieron cargar las métricas: {{ overviewError }}
        <button type="button" class="ml-2 underline hover:text-brass" @click="refresh">Reintentar</button>
      </p>
      <p
        v-if="overview && !overview.metrics_enabled"
        class="rounded-lg border border-ambar/40 bg-ambar/10 px-4 py-3 text-sm"
        role="status"
      >
        La medición está desactivada en el servidor (METRICS_ENABLED). Solo verás los registros guardados antes.
      </p>
      <p
        v-if="overview?.truncated"
        class="rounded-lg border border-ambar/40 bg-ambar/10 px-4 py-3 text-sm"
        role="status"
      >
        Hay más peticiones de las que se pueden resumir de una vez; se han usado las más recientes. Elige un periodo más
        corto para ver todo.
      </p>

      <p v-if="!overview && !overviewError" class="py-24 text-center text-sm text-paper/60">Cargando métricas…</p>

      <template v-if="overview">
        <p
          v-if="!hasData"
          class="rounded-xl border border-paper/15 bg-ink-light/50 px-6 py-8 text-center text-sm text-paper/70"
        >
          Aún no hay peticiones medidas en
          {{ rangeLabel.toLowerCase() === 'todo' ? 'el historial' : `las últimas ${rangeLabel.toLowerCase()}` }}. Genera
          un informe o escribe en el chat y vuelve a actualizar.
        </p>

        <!-- Everything below dims (not blanks) while a reload runs -->
        <div
          class="space-y-6 transition-opacity duration-200"
          :class="{ 'opacity-60': dimmed }"
          :aria-busy="overviewLoading"
        >
          <!-- KPI tiles -->
          <section class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6" aria-label="Resumen">
            <KpiCard
              v-for="t in tiles"
              :key="t.key"
              :label="t.label"
              :value="t.value"
              :hint="t.hint"
              :trend="t.trend"
              :tone="t.tone"
              :color="t.color"
            />
          </section>

          <!-- Traffic -->
          <ChartCard
            :title="`Peticiones por ${bucketWord}`"
            subtitle="Volumen y peticiones con error"
            :empty="!hasData"
            :table="trafficTable"
          >
            <EChart :option="trafficOption" height="280px" label="Peticiones y errores a lo largo del tiempo" />
          </ChartCard>

          <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <ChartCard
              title="Latencia en el tiempo"
              subtitle="Duración total de la petición: media y percentil 95"
              :empty="!hasData"
              :table="latencyTable"
            >
              <EChart :option="latencyOption" label="Latencia media y p95 a lo largo del tiempo" />
            </ChartCard>

            <ChartCard
              title="Distribución de la latencia"
              subtitle="Cuántas peticiones caen en cada tramo de duración"
              :empty="!hasData"
              :table="histogramTable"
            >
              <EChart :option="histogramOption" label="Histograma de la latencia" />
            </ChartCard>

            <ChartCard
              title="Tokens"
              :subtitle="`Entrada y salida por ${bucketWord}`"
              :empty="!hasData"
              :table="tokensTable"
            >
              <EChart :option="tokensOption" label="Tokens de entrada y salida a lo largo del tiempo" />
            </ChartCard>

            <ChartCard
              title="Coste"
              :subtitle="`Gasto estimado por ${bucketWord}. Solo cuenta las peticiones con tarifa`"
              :empty="!hasData"
              :table="costTable"
            >
              <EChart :option="costOption" label="Coste a lo largo del tiempo" />
            </ChartCard>

            <ChartCard
              title="Tiempo medio por actor"
              subtitle="Agente, LLM, RAG, base de datos y servicios externos"
              :empty="!actors.length"
              :table="actorTable"
            >
              <EChart
                :option="actorOption"
                :height="`${Math.max(180, actors.length * 44 + 16)}px`"
                label="Duración media por actor"
              />
            </ChartCard>

            <ChartCard
              title="Pasos que más tiempo acumulan"
              subtitle="Suma de la duración de cada paso. Un paso puede contener a otros"
              :empty="!spans.length"
              :table="spansTable"
            >
              <EChart
                :option="spansOption"
                :height="`${Math.max(180, spans.length * 32 + 16)}px`"
                label="Pasos con más tiempo acumulado"
              />
            </ChartCard>

            <!-- Health: two meters -->
            <ChartCard
              title="Estado de las peticiones"
              subtitle="Reparto entre correctas, con error y canceladas"
              :empty="!hasData"
            >
              <div
                class="flex h-3 gap-[2px] overflow-hidden rounded"
                role="img"
                :aria-label="statusBar.map((s) => `${s.label}: ${s.count}`).join(', ')"
              >
                <span
                  v-for="s in statusBar"
                  :key="s.key"
                  class="h-full rounded-sm"
                  :style="{ width: `${s.share}%`, backgroundColor: s.color }"
                  :title="`${s.label}: ${formatNumber(s.count)} (${formatPercent(s.share / 100)})`"
                />
              </div>
              <ul class="mt-4 space-y-2 text-sm">
                <li v-for="s in statusBar" :key="s.key" class="flex items-center gap-2">
                  <span class="h-2.5 w-2.5 rounded-full" :style="{ backgroundColor: s.color }" />
                  <span class="text-paper/80">{{ s.label }}</span>
                  <span class="ml-auto font-semibold tabular-nums">{{ formatNumber(s.count) }}</span>
                  <span class="w-16 text-right text-xs text-paper/50 tabular-nums">{{
                    formatPercent(s.share / 100)
                  }}</span>
                </li>
              </ul>

              <div class="mt-6 border-t border-paper/10 pt-4">
                <p class="text-xs text-paper/60">Aciertos de caché (pasos que informan si la usaron)</p>
                <div class="mt-2 flex items-center gap-3">
                  <div
                    class="h-2 flex-1 overflow-hidden rounded bg-paper/10"
                    role="meter"
                    :aria-valuenow="cache.hits"
                    aria-valuemin="0"
                    :aria-valuemax="cache.total"
                  >
                    <div
                      class="h-full rounded"
                      :style="{ width: `${(cacheRate ?? 0) * 100}%`, backgroundColor: COLORS.cache }"
                    />
                  </div>
                  <span class="w-14 text-right text-sm font-semibold tabular-nums">{{
                    formatPercent(cacheRate, 0)
                  }}</span>
                </div>
                <p class="mt-1 text-[11px] text-paper/50 tabular-nums">
                  {{ formatNumber(cache.hits) }} de {{ formatNumber(cache.total) }}
                </p>
              </div>
            </ChartCard>

            <ChartCard
              title="Errores más frecuentes"
              subtitle="Clase de la excepción en los pasos que fallaron"
              :empty="!errors.length"
              empty-text="Ningún paso ha fallado en este periodo."
              :table="errorsTable"
            >
              <EChart
                :option="errorsOption"
                :height="`${Math.max(160, errors.length * 40 + 16)}px`"
                label="Errores más frecuentes"
              />
            </ChartCard>
          </div>

          <!-- Breakdown tables -->
          <div class="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <ChartCard title="Por ruta" subtitle="Qué endpoints se usan más y cuáles tardan" :empty="!hasData">
              <div class="overflow-x-auto">
                <table class="w-full min-w-[34rem] text-left text-xs">
                  <thead class="text-paper/60">
                    <tr class="border-b border-paper/15">
                      <th scope="col" class="px-2 py-1.5 font-medium">Ruta</th>
                      <th scope="col" class="px-2 py-1.5 text-right font-medium">Peticiones</th>
                      <th scope="col" class="px-2 py-1.5 text-right font-medium">Errores</th>
                      <th scope="col" class="px-2 py-1.5 text-right font-medium">Media</th>
                      <th scope="col" class="px-2 py-1.5 text-right font-medium">p95</th>
                      <th scope="col" class="px-2 py-1.5 text-right font-medium">Coste</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="r in overview.by_route" :key="r.route" class="border-b border-paper/10">
                      <td class="px-2 py-1.5 font-mono text-[11px] text-paper/90">{{ r.route }}</td>
                      <td class="px-2 py-1.5 text-right tabular-nums">{{ formatNumber(r.requests) }}</td>
                      <td class="px-2 py-1.5 text-right tabular-nums">{{ formatNumber(r.errors) }}</td>
                      <td class="px-2 py-1.5 text-right tabular-nums">{{ formatMs(r.avg_ms) }}</td>
                      <td class="px-2 py-1.5 text-right tabular-nums">{{ formatMs(r.p95_ms) }}</td>
                      <td class="px-2 py-1.5 text-right tabular-nums">{{ groupCost(r) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </ChartCard>

            <ChartCard title="Por modelo" subtitle="Uso y gasto de cada modelo de lenguaje" :empty="!hasData">
              <div class="overflow-x-auto">
                <table class="w-full min-w-[34rem] text-left text-xs">
                  <thead class="text-paper/60">
                    <tr class="border-b border-paper/15">
                      <th scope="col" class="px-2 py-1.5 font-medium">Modelo</th>
                      <th scope="col" class="px-2 py-1.5 text-right font-medium">Peticiones</th>
                      <th scope="col" class="px-2 py-1.5 text-right font-medium">Tokens ent.</th>
                      <th scope="col" class="px-2 py-1.5 text-right font-medium">Tokens sal.</th>
                      <th scope="col" class="px-2 py-1.5 text-right font-medium">Media</th>
                      <th scope="col" class="px-2 py-1.5 text-right font-medium">Coste</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="m in overview.by_model" :key="m.model" class="border-b border-paper/10">
                      <td class="max-w-[14rem] truncate px-2 py-1.5 text-paper/90" :title="m.model">
                        {{ m.model === 'unknown' ? 'Sin modelo' : m.model }}
                      </td>
                      <td class="px-2 py-1.5 text-right tabular-nums">{{ formatNumber(m.requests) }}</td>
                      <td class="px-2 py-1.5 text-right tabular-nums">{{ formatNumber(m.tokens_in) }}</td>
                      <td class="px-2 py-1.5 text-right tabular-nums">{{ formatNumber(m.tokens_out) }}</td>
                      <td class="px-2 py-1.5 text-right tabular-nums">{{ formatMs(m.avg_ms) }}</td>
                      <td class="px-2 py-1.5 text-right tabular-nums">{{ groupCost(m) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </ChartCard>
          </div>
        </div>

        <!-- Records -->
        <RequestsTable
          :page="page"
          :loading="pageLoading"
          :error="pageError"
          :filters="filters"
          :routes="routeOptions"
          :models="modelOptions"
          :eur-per-usd="rate"
          :page-size="PAGE_SIZE"
          @set-filter="setFilter"
          @sort="setSort"
          @offset="goToOffset"
          @select="selectedId = $event.id"
        />
      </template>
    </div>

    <RequestDetail :request-id="selectedId" :eur-per-usd="rate" @close="selectedId = null" />
  </main>
</template>
