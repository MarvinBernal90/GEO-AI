<!--
==============================================================================
RAG QUALITY PANEL ("Calidad RAG" TAB OF "/metrics")
==============================================================================
File: frontend/src/components/metrics/RagEvalsPanel.vue

Reads the evaluation runs saved by the harness (GET /api/evals/*) and answers three questions:
  - How good is the retrieval? hit@k, MRR and nDCG, with the interval that the small question set allows
  - How good are the answers? fact recall, faithfulness, abstention, citations, language
  - What is in the corpus, and what is missing from it?

Runs are only comparable inside one question set, so one set is shown at a time. The "Reserva"
(holdout) set is for confirming a choice made on "Desarrollo", never for tuning.
Every number shown next to an interval means: with this few questions the real value could be anywhere inside it.
The data comes from useRagEvals().
-->
<script setup>
import { computed, ref } from 'vue'

import ChartCard from './ChartCard.vue'
import EChart from './EChart.vue'
import KpiCard from './KpiCard.vue'
import { SETS, useRagEvals } from '../../composables/useRagEvals.js'
import {
  BAR_MAX_WIDTH,
  BAR_RADIUS_UP,
  INK,
  SERIES,
  baseOption,
  categoryAxis,
  tooltipHtml,
  valueAxis,
} from '../../utils/chartTheme.js'
import { formatDateTime, formatNumber, formatPercent } from '../../utils/format.js'

const {
  runs,
  loading,
  error,
  selectedSet,
  selectedId,
  selected,
  setRuns,
  setCounts,
  detail,
  detailLoading,
  detailError,
  corpus,
  select,
  reload,
} = useRagEvals()

// ---------------------------------------------------------------- formatting
const pct = (v, digits = 0) => formatPercent(v, digits)
const num2 = (v) => (typeof v === 'number' ? v.toFixed(2) : '—')
const interval = (m) => (m && typeof m.value === 'number' ? `IC 95 %: ${pct(m.lo)} – ${pct(m.hi)} · n=${m.n}` : '')
const val = (m) => (m && typeof m.value === 'number' ? m.value : null)

const FAILURE_LABEL = {
  retrieval_miss: 'No recuperó el artículo',
  over_abstention: 'Se negó a responder',
  unsupported: 'Afirmaciones sin respaldo',
  generation_error: 'Respuesta incompleta',
  wrongly_answered: 'Respondió sin cobertura',
}
const FAILURE_HELP = {
  retrieval_miss: 'El artículo correcto no está entre los 6 primeros resultados: el modelo nunca vio la respuesta.',
  over_abstention: 'El artículo estaba, pero el modelo dijo que no tenía información.',
  unsupported: 'El juez o el verificador de citas encontró algo que el contexto no respalda.',
  generation_error: 'Tenía el artículo y respondió, pero faltan hechos clave.',
  wrongly_answered: 'La pregunta no tiene respuesta en el corpus y aun así el modelo respondió.',
}
const LANG_LABEL = { es: 'castellano', ca: 'catalán', en: 'inglés', unknown: '¿?' }
const directionLabel = (d) =>
  d
    .split('→')
    .map((x) => LANG_LABEL[x] ?? x)
    .join(' → ')

// ---------------------------------------------------------------- run description
function describe(run) {
  const c = run.config ?? {}
  const parts = ['Titan v2']
  if (c.rerank) parts.push('+ rerank')
  if (c.rewrite === 'ca') parts.push('+ reescritura a catalán')
  return parts.join(' ')
}

// ---------------------------------------------------------------- comparison table
const COLUMNS = [
  { key: 'hit@1', label: 'Hit@1', get: (r) => val(r.retrieval?.['hit@1']) },
  { key: 'hit@3', label: 'Hit@3', get: (r) => val(r.retrieval?.['hit@3']) },
  { key: 'hit@6', label: 'Hit@6', get: (r) => val(r.retrieval?.['hit@6']) },
  { key: 'mrr', label: 'MRR', get: (r) => val(r.retrieval?.mrr) },
  { key: 'recall', label: 'Hechos', get: (r) => val(r.answers?.fact_recall) },
  { key: 'faith', label: 'Fidelidad', get: (r) => val(r.answers?.faithfulness) },
]
const best = computed(() => {
  const out = {}
  for (const col of COLUMNS) {
    const values = setRuns.value.map(col.get).filter((v) => v !== null)
    out[col.key] = values.length > 1 ? Math.max(...values) : null
  }
  return out
})

// ---------------------------------------------------------------- charts
const compareOption = computed(() => {
  const list = [...setRuns.value].reverse()
  const base = baseOption({ legend: true })
  const bar = (name, get, color) => ({
    name,
    type: 'bar',
    barMaxWidth: BAR_MAX_WIDTH,
    itemStyle: { color, borderRadius: BAR_RADIUS_UP },
    data: list.map(get),
  })
  return {
    ...base,
    // Every configuration needs its label: with the default "hide overlapping labels" only every other one showed.
    xAxis: categoryAxis(
      list.map((r) => r.name),
      {
        axisLabel: { color: INK.muted, fontSize: 11, interval: 0, hideOverlap: false, width: 96, overflow: 'break' },
      },
    ),
    yAxis: valueAxis((v) => `${Math.round(v * 100)} %`, { min: 0, max: 1 }),
    tooltip: {
      ...base.tooltip,
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(245, 241, 232, 0.05)' } },
      formatter: (params) =>
        tooltipHtml(
          params[0]?.axisValueLabel ?? '',
          params.map((p) => ({ color: p.color, name: p.seriesName, value: pct(p.value, 1) })),
        ),
    },
    series: [
      bar('Hit@1', (r) => val(r.retrieval?.['hit@1']), SERIES[3]),
      bar('Hit@3', (r) => val(r.retrieval?.['hit@3']), SERIES[0]),
      bar('Hit@6', (r) => val(r.retrieval?.['hit@6']), SERIES[2]),
      bar('MRR', (r) => val(r.retrieval?.mrr), SERIES[1]),
    ],
  }
})
const compareTable = computed(() => ({
  columns: [
    { key: 'name', label: 'Configuración' },
    ...['Hit@1', 'Hit@3', 'Hit@6', 'MRR'].map((l) => ({ key: l, label: l, align: 'right' })),
  ],
  rows: setRuns.value.map((r) => ({
    name: r.name,
    'Hit@1': pct(val(r.retrieval?.['hit@1']), 1),
    'Hit@3': pct(val(r.retrieval?.['hit@3']), 1),
    'Hit@6': pct(val(r.retrieval?.['hit@6']), 1),
    MRR: num2(val(r.retrieval?.mrr)),
  })),
}))

const failureEntries = computed(() => Object.entries(selected.value?.failures ?? {}).sort((a, b) => b[1] - a[1]))
const failureOption = computed(() => {
  const base = baseOption()
  const entries = failureEntries.value
  return {
    ...base,
    grid: { ...base.grid, left: 8 },
    xAxis: valueAxis(String, { minInterval: 1 }),
    yAxis: { ...categoryAxis(entries.map(([k]) => FAILURE_LABEL[k] ?? k)), inverse: true },
    tooltip: {
      ...base.tooltip,
      trigger: 'item',
      formatter: (p) => tooltipHtml(p.name, [{ color: SERIES[1], name: 'preguntas', value: String(p.value) }]),
    },
    series: [
      {
        type: 'bar',
        barMaxWidth: BAR_MAX_WIDTH,
        itemStyle: { color: SERIES[1], borderRadius: [0, 4, 4, 0] },
        data: entries.map(([, n]) => n),
        label: { show: true, position: 'right', color: INK.secondary, fontSize: 11 },
      },
    ],
  }
})
const failureTable = computed(() => ({
  columns: [
    { key: 'tipo', label: 'Tipo de fallo' },
    { key: 'n', label: 'Preguntas', align: 'right' },
  ],
  rows: failureEntries.value.map(([k, n]) => ({ tipo: FAILURE_LABEL[k] ?? k, n })),
}))

// ---------------------------------------------------------------- slices
const directionRows = computed(() => {
  const slice = selected.value?.slices?.direction ?? {}
  return Object.entries(slice).map(([k, v]) => ({
    key: k,
    label: directionLabel(k),
    n: v['hit@3']?.n ?? 0,
    hit3: val(v['hit@3']),
    hit6: val(v['hit@6']),
    mrr: val(v.mrr),
    lo: v['hit@3']?.lo,
    hi: v['hit@3']?.hi,
  }))
})
const kindRows = computed(() =>
  Object.entries(selected.value?.slices?.kind ?? {}).map(([k, v]) => ({
    key: k,
    n: v['hit@3']?.n ?? 0,
    hit3: val(v['hit@3']),
    hit6: val(v['hit@6']),
  })),
)
const KIND_LABEL = {
  single: 'Pregunta sobre un artículo',
  pgm: 'Urbanismo (PGM) sin zona',
  pgm_zone: 'Urbanismo (PGM) con zona',
  catalan_question: 'Pregunta en catalán',
}

// ---------------------------------------------------------------- questions
const onlyFailures = ref(true)
const expanded = ref(null)
const questions = computed(() => {
  const all = detail.value?.questions ?? []
  return onlyFailures.value ? all.filter((q) => q.failure) : all
})
const toggle = (id) => (expanded.value = expanded.value === id ? null : id)
const rankText = (q) => (!q.answerable ? 'sin respuesta' : q.rank_of_gold ? `#${q.rank_of_gold}` : 'fuera del top 10')
const missingFacts = (q) => (q.facts ?? []).filter((_, i) => q.judge && q.judge.facts_present?.[i] === false)

// ---------------------------------------------------------------- corpus
const corpusWarnings = computed(() => {
  const c = corpus.value
  if (!c) return []
  const out = []
  for (const e of c.empty_sources ?? [])
    out.push(`«${e.fuente_legal.slice(0, 70)}» no aporta ningún fragmento: ${e.note || e.error}.`)
  if (c.oversized_chunks)
    out.push(
      `${c.oversized_chunks} fragmentos superan el límite de entrada del modelo de embeddings y se recortan al indexar.`,
    )
  for (const s of c.skipped_files ?? []) out.push(`No se carga «${s.file.slice(0, 60)}»: ${s.note}.`)
  return out
})
const corpusTable = computed(() => ({
  columns: [
    { key: 'fuente', label: 'Norma' },
    { key: 'lang', label: 'Idioma' },
    { key: 'chunks', label: 'Fragmentos', align: 'right' },
    { key: 'max', label: 'Mayor (car.)', align: 'right' },
  ],
  rows: (corpus.value?.sources ?? []).map((s) => ({
    fuente: s.fuente_legal.length > 80 ? `${s.fuente_legal.slice(0, 80)}…` : s.fuente_legal,
    lang: LANG_LABEL[s.lang] ?? s.lang,
    chunks: s.chunks,
    max: formatNumber(s.max_chars),
  })),
}))

const a = computed(() => selected.value?.answers)
const r = computed(() => selected.value?.retrieval)
const signal = computed(() => selected.value?.abstention_signal)
</script>

<template>
  <div class="space-y-6">
    <!-- Intro and refresh -->
    <div class="flex flex-wrap items-start justify-between gap-4">
      <p class="max-w-3xl text-sm leading-relaxed text-paper/70">
        Cada configuración se prueba con preguntas cuya respuesta correcta se conoce. Mide si el sistema encuentra el
        artículo adecuado, si lo usa bien al responder y si se calla cuando el corpus no cubre la pregunta.
      </p>
      <button
        type="button"
        class="rounded border border-paper/20 px-3 py-1.5 text-xs text-paper/80 transition hover:border-brass hover:text-brass focus:ring-2 focus:ring-brass/50 focus:outline-none disabled:opacity-40"
        :disabled="loading"
        @click="reload"
      >
        {{ loading ? 'Actualizando…' : 'Actualizar' }}
      </button>
    </div>

    <p v-if="error" class="rounded-lg border border-rojo/40 bg-rojo/10 px-4 py-3 text-sm" role="alert">
      No se pudieron cargar las evaluaciones: {{ error }}
      <button type="button" class="ml-2 underline hover:text-brass" @click="reload">Reintentar</button>
    </p>
    <p v-if="loading && !runs.length" class="py-24 text-center text-sm text-paper/60">Cargando evaluaciones…</p>

    <p
      v-if="!loading && !error && !runs.length"
      class="rounded-xl border border-paper/15 bg-ink-light/50 px-6 py-8 text-center text-sm text-paper/70"
    >
      Aún no hay evaluaciones. Ejecuta
      <code class="rounded bg-ink px-1.5 py-0.5 font-mono text-xs">python -m evals.run_eval --set dev</code>
      y vuelve a actualizar. Guía completa en <code class="font-mono text-xs">evals/README.md</code>.
    </p>

    <template v-if="runs.length">
      <!-- Set selector -->
      <div class="flex flex-wrap items-center gap-3" role="group" aria-label="Conjunto de preguntas">
        <span class="text-xs tracking-wider text-paper/50 uppercase">Preguntas</span>
        <div class="inline-flex overflow-hidden rounded-lg border border-paper/20">
          <button
            v-for="s in SETS"
            :key="s.value"
            type="button"
            class="px-3.5 py-1.5 text-xs transition focus:ring-2 focus:ring-brass/50 focus:outline-none focus-visible:ring-inset"
            :class="
              selectedSet === s.value
                ? 'bg-brass text-ink font-semibold'
                : 'text-paper/70 hover:bg-paper/10 hover:text-paper'
            "
            :aria-pressed="selectedSet === s.value"
            :title="s.hint"
            @click="selectedSet = s.value"
          >
            {{ s.label }} ({{ setCounts[s.value] ?? 0 }})
          </button>
        </div>
        <span class="text-xs text-paper/50">{{ SETS.find((s) => s.value === selectedSet)?.hint }}</span>
      </div>

      <p
        v-if="!setRuns.length"
        class="rounded-xl border border-paper/15 bg-ink-light/50 px-6 py-6 text-center text-sm text-paper/70"
      >
        No hay ejecuciones de este conjunto todavía.
      </p>

      <template v-if="selected">
        <!-- Headline numbers of the selected run -->
        <section aria-label="Resultado de la ejecución seleccionada" class="space-y-3">
          <p class="text-sm text-paper/70">
            Ejecución <strong class="text-paper">{{ selected.name }}</strong> · {{ describe(selected) }} ·
            {{ selected.n_answerable }} preguntas con respuesta y {{ selected.n_unanswerable }} sin ella ·
            {{ formatDateTime(selected.created_at) }}
          </p>
          <div class="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
            <KpiCard
              label="Encuentra el artículo (top 3)"
              :value="pct(val(r['hit@3']))"
              :hint="interval(r['hit@3'])"
              :tone="val(r['hit@3']) >= 0.9 ? 'good' : val(r['hit@3']) < 0.7 ? 'critical' : 'default'"
            />
            <KpiCard label="Encuentra el artículo (top 6)" :value="pct(val(r['hit@6']))" :hint="interval(r['hit@6'])" />
            <KpiCard label="Posición media (MRR)" :value="num2(val(r.mrr))" hint="1,00 = siempre el primero" />
            <KpiCard
              label="Hechos clave en la respuesta"
              :value="a ? pct(val(a.fact_recall)) : '—'"
              :hint="a ? interval(a.fact_recall) : 'Ejecuta con --answers'"
            />
            <KpiCard
              label="Respuestas sin nada inventado"
              :value="a ? pct(val(a.faithfulness)) : '—'"
              :hint="a ? interval(a.faithfulness) : 'Ejecuta con --answers'"
              :tone="a && val(a.faithfulness) < 0.8 ? 'critical' : 'default'"
            />
            <KpiCard
              label="Se calla si no hay cobertura"
              :value="a ? pct(val(a.correct_abstention)) : '—'"
              :hint="a ? interval(a.correct_abstention) : 'Ejecuta con --answers'"
            />
          </div>
        </section>

        <div class="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <ChartCard
            title="Comparación de configuraciones"
            subtitle="Misma batería de preguntas; más alto es mejor"
            :empty="setRuns.length < 1"
            :table="compareTable"
          >
            <EChart :option="compareOption" height="300px" label="Hit@1, Hit@3, Hit@6 y MRR por configuración" />
          </ChartCard>
          <ChartCard
            title="Dónde falla"
            subtitle="Preguntas de la ejecución seleccionada, por causa"
            :empty="!failureEntries.length"
            empty-text="Sin fallos en esta ejecución."
            :table="failureTable"
          >
            <EChart :option="failureOption" height="300px" label="Fallos por causa" />
            <ul class="mt-3 space-y-1 text-xs text-paper/60">
              <li v-for="[k] in failureEntries" :key="k">
                <strong class="text-paper/80">{{ FAILURE_LABEL[k] ?? k }}:</strong> {{ FAILURE_HELP[k] }}
              </li>
            </ul>
          </ChartCard>
        </div>

        <!-- Comparison table -->
        <section class="rounded-xl border border-paper/15 bg-ink-light/50 p-4 shadow-lg" aria-label="Ejecuciones">
          <h2 class="text-sm font-semibold text-paper">Ejecuciones de este conjunto</h2>
          <p class="mt-1 text-xs text-paper/60">
            Pulsa una fila para ver su detalle. En negrita, el mejor valor de cada columna.
          </p>
          <div class="mt-3 overflow-x-auto">
            <table class="w-full min-w-[720px] text-left text-sm">
              <thead class="text-xs text-paper/50">
                <tr>
                  <th class="py-2 pr-3 font-normal">Configuración</th>
                  <th v-for="c in COLUMNS" :key="c.key" class="px-2 py-2 text-right font-normal">{{ c.label }}</th>
                  <th class="py-2 pl-3 font-normal">Fecha</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="run in setRuns"
                  :key="run.run_id"
                  class="cursor-pointer border-t border-paper/10 transition hover:bg-paper/5"
                  :class="{ 'bg-paper/10': run.run_id === selectedId }"
                  tabindex="0"
                  :aria-selected="run.run_id === selectedId"
                  @click="select(run.run_id)"
                  @keydown.enter="select(run.run_id)"
                >
                  <td class="py-2 pr-3">
                    <span class="font-medium text-paper">{{ run.name }}</span>
                    <span class="block text-xs text-paper/50">{{ describe(run) }}</span>
                  </td>
                  <td
                    v-for="c in COLUMNS"
                    :key="c.key"
                    class="px-2 py-2 text-right tabular-nums"
                    :class="
                      c.get(run) !== null && c.get(run) === best[c.key] ? 'font-bold text-paper' : 'text-paper/70'
                    "
                  >
                    {{ c.key === 'mrr' ? num2(c.get(run)) : pct(c.get(run)) }}
                  </td>
                  <td class="py-2 pl-3 text-xs whitespace-nowrap text-paper/50">
                    {{ formatDateTime(run.created_at) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="mt-3 text-xs text-paper/50">
            Con {{ selected.n_answerable }} preguntas, diferencias de unos pocos puntos entran dentro del margen de
            error (ver el intervalo en cada tarjeta). Una mejora solo es fiable si se mantiene en «Reserva».
          </p>
        </section>

        <div class="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <!-- Language direction -->
          <section class="rounded-xl border border-paper/15 bg-ink-light/50 p-4 shadow-lg" aria-label="Idioma">
            <h2 class="text-sm font-semibold text-paper">¿Importa el idioma?</h2>
            <p class="mt-1 text-xs text-paper/60">
              Acierto en el top 3 según el idioma de la pregunta → el del artículo.
            </p>
            <table class="mt-3 w-full text-left text-sm">
              <thead class="text-xs text-paper/50">
                <tr>
                  <th class="py-1 font-normal">Pregunta → artículo</th>
                  <th class="py-1 text-right font-normal">Preguntas</th>
                  <th class="py-1 text-right font-normal">Hit@3</th>
                  <th class="py-1 text-right font-normal">Hit@6</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in directionRows" :key="row.key" class="border-t border-paper/10">
                  <td class="py-1.5 text-paper">{{ row.label }}</td>
                  <td class="py-1.5 text-right tabular-nums text-paper/70">{{ row.n }}</td>
                  <td
                    class="py-1.5 text-right tabular-nums text-paper"
                    :title="`IC 95 %: ${pct(row.lo)} – ${pct(row.hi)}`"
                  >
                    {{ pct(row.hit3) }}
                  </td>
                  <td class="py-1.5 text-right tabular-nums text-paper/70">{{ pct(row.hit6) }}</td>
                </tr>
              </tbody>
            </table>
            <p class="mt-3 text-xs text-paper/50">
              Grupos con menos de 10 preguntas son orientativos. «castellano → catalán» es el caso habitual del
              producto: el usuario pregunta en castellano y la normativa urbanística está en catalán.
            </p>
            <table v-if="kindRows.length" class="mt-4 w-full text-left text-sm">
              <thead class="text-xs text-paper/50">
                <tr>
                  <th class="py-1 font-normal">Tipo de pregunta</th>
                  <th class="py-1 text-right font-normal">Preguntas</th>
                  <th class="py-1 text-right font-normal">Hit@3</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in kindRows" :key="row.key" class="border-t border-paper/10">
                  <td class="py-1.5 text-paper">{{ KIND_LABEL[row.key] ?? row.key }}</td>
                  <td class="py-1.5 text-right tabular-nums text-paper/70">{{ row.n }}</td>
                  <td class="py-1.5 text-right tabular-nums text-paper">{{ pct(row.hit3) }}</td>
                </tr>
              </tbody>
            </table>
          </section>

          <!-- Answer quality + abstention -->
          <section
            class="rounded-xl border border-paper/15 bg-ink-light/50 p-4 shadow-lg"
            aria-label="Calidad de las respuestas"
          >
            <h2 class="text-sm font-semibold text-paper">Calidad de las respuestas</h2>
            <p v-if="!a" class="mt-3 text-sm text-paper/60">
              Esta ejecución solo midió la recuperación. Añade <code class="font-mono text-xs">--answers</code> para
              generar y juzgar respuestas.
            </p>
            <dl v-else class="mt-3 grid grid-cols-[1fr_auto] gap-x-4 gap-y-2 text-sm">
              <dt class="text-paper/70">
                Citas que existen en el contexto
                <span class="block text-xs text-paper/40">artículos citados que sí se le dieron al modelo</span>
              </dt>
              <dd class="text-right tabular-nums text-paper" :title="interval(a.citation_validity)">
                {{ pct(val(a.citation_validity)) }}
              </dd>
              <dt class="text-paper/70">Responde en el idioma de la pregunta</dt>
              <dd class="text-right tabular-nums text-paper" :title="interval(a.answer_language)">
                {{ pct(val(a.answer_language)) }}
              </dd>
              <dt class="text-paper/70">Se niega a responder teniendo el artículo</dt>
              <dd class="text-right tabular-nums text-paper" :title="interval(a.over_abstention)">
                {{ pct(val(a.over_abstention)) }}
              </dd>
              <dt class="text-paper/70">Tiempo de respuesta (mediana / p95)</dt>
              <dd class="text-right tabular-nums text-paper">
                {{ a.latency_p50_s?.toFixed(1) ?? '—' }} s / {{ a.latency_p95_s?.toFixed(1) ?? '—' }} s
              </dd>
            </dl>
            <div v-if="signal" class="mt-5 border-t border-paper/10 pt-4">
              <h3 class="text-xs font-semibold text-paper">¿Basta la distancia para saber si hay cobertura?</h3>
              <p class="mt-1 text-2xl font-semibold text-paper tabular-nums">{{ num2(signal.auroc) }}</p>
              <p class="mt-1 text-xs text-paper/60">
                Probabilidad de que una pregunta con respuesta quede más cerca de su artículo que una sin respuesta
                (0,50 = azar; 1,00 = un umbral las separa sin error). Mediana de distancia:
                {{ num2(signal.answerable_median_distance) }} con respuesta frente a
                {{ num2(signal.unanswerable_median_distance) }} sin ella ({{ signal.n_answerable }} y
                {{ signal.n_unanswerable }} preguntas).
              </p>
            </div>
          </section>
        </div>

        <!-- Corpus -->
        <section
          v-if="corpus"
          class="rounded-xl border border-paper/15 bg-ink-light/50 p-4 shadow-lg"
          aria-label="Corpus"
        >
          <h2 class="text-sm font-semibold text-paper">Qué contiene el corpus de pruebas</h2>
          <p class="mt-1 text-xs text-paper/60">
            {{ formatNumber(corpus.total_chunks) }} fragmentos de {{ corpus.sources.length }} normas. Idioma de los
            fragmentos:
            {{
              Object.entries(corpus.lang_chunks)
                .map(([k, n]) => `${LANG_LABEL[k] ?? k} ${n}`)
                .join(' · ')
            }}.
          </p>
          <ul v-if="corpusWarnings.length" class="mt-3 space-y-1.5" role="list">
            <li
              v-for="w in corpusWarnings"
              :key="w"
              class="rounded-lg border border-ambar/40 bg-ambar/10 px-3 py-2 text-xs text-paper/90"
            >
              ⚠ {{ w }}
            </li>
          </ul>
          <div class="mt-3 overflow-x-auto">
            <table class="w-full min-w-[560px] text-left text-sm">
              <thead class="text-xs text-paper/50">
                <tr>
                  <th
                    v-for="c in corpusTable.columns"
                    :key="c.key"
                    class="py-1.5 font-normal"
                    :class="{ 'text-right': c.align === 'right' }"
                  >
                    {{ c.label }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in corpusTable.rows" :key="row.fuente" class="border-t border-paper/10">
                  <td
                    v-for="c in corpusTable.columns"
                    :key="c.key"
                    class="py-1.5"
                    :class="c.align === 'right' ? 'text-right tabular-nums text-paper/70' : 'text-paper'"
                  >
                    {{ row[c.key] }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- Questions -->
        <section class="rounded-xl border border-paper/15 bg-ink-light/50 p-4 shadow-lg" aria-label="Preguntas">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <h2 class="text-sm font-semibold text-paper">Pregunta por pregunta</h2>
            <label class="flex cursor-pointer items-center gap-2 text-xs text-paper/70">
              <input v-model="onlyFailures" type="checkbox" class="accent-brass" /> Solo las que fallan
            </label>
          </div>
          <p v-if="detailLoading" class="mt-4 text-sm text-paper/60">Cargando el detalle…</p>
          <p v-else-if="detailError" class="mt-4 text-sm text-rojo" role="alert">
            No se pudo cargar el detalle: {{ detailError }}
          </p>
          <p v-else-if="!questions.length" class="mt-4 text-sm text-paper/60">
            {{ onlyFailures ? 'Ninguna pregunta falla en esta ejecución.' : 'Sin preguntas.' }}
          </p>
          <ul v-else class="mt-3 divide-y divide-paper/10" role="list">
            <li v-for="q in questions" :key="q.id">
              <button
                type="button"
                class="flex w-full items-start gap-3 py-2.5 text-left transition hover:bg-paper/5 focus:ring-2 focus:ring-brass/50 focus:outline-none"
                :aria-expanded="expanded === q.id"
                @click="toggle(q.id)"
              >
                <span class="mt-0.5 w-14 shrink-0 font-mono text-xs text-paper/50">{{ q.id }}</span>
                <span class="min-w-0 flex-1 text-sm text-paper">{{ q.question }}</span>
                <span class="hidden shrink-0 text-xs text-paper/60 sm:block">{{ rankText(q) }}</span>
                <span
                  class="shrink-0 rounded-full px-2 py-0.5 text-[11px]"
                  :class="q.failure ? 'bg-rojo/20 text-paper' : 'bg-verde/25 text-paper'"
                >
                  {{ q.failure ? (FAILURE_LABEL[q.failure] ?? q.failure) : 'Correcta' }}
                </span>
              </button>
              <div v-if="expanded === q.id" class="space-y-3 pb-4 pl-[4.25rem] text-sm">
                <p class="text-xs text-paper/50">
                  {{ directionLabel(q.direction ?? `${q.lang}→${q.lang}`)
                  }}<span v-if="q.zona_pgm"> · zona {{ q.zona_pgm }}</span
                  ><span v-if="q.query_used"> · búsqueda reescrita: «{{ q.query_used }}»</span>
                </p>
                <div>
                  <p class="text-xs tracking-wider text-paper/50 uppercase">
                    Artículos recuperados (más cercano primero)
                  </p>
                  <ol class="mt-1 space-y-0.5">
                    <li
                      v-for="(t, i) in q.top"
                      :key="i"
                      class="flex gap-2 text-xs"
                      :class="t.is_gold ? 'text-paper' : 'text-paper/60'"
                    >
                      <span class="w-4 shrink-0 tabular-nums">{{ i + 1 }}.</span>
                      <span class="min-w-0 flex-1 truncate"
                        >{{ t.fuente_legal.slice(0, 48) }} · art. {{ t.numero_articulo }} — {{ t.titulo }}</span
                      >
                      <span class="shrink-0 tabular-nums">{{ t.distance.toFixed(3) }}</span>
                      <span v-if="t.is_gold" class="shrink-0 text-verde" title="Es el artículo correcto"
                        >✔ correcto</span
                      >
                    </li>
                  </ol>
                  <p v-if="q.answerable && !q.top.some((t) => t.is_gold)" class="mt-1 text-xs text-paper/60">
                    Esperado: {{ q.gold.map((g) => `${g[0].slice(0, 48)} · art. ${g[1]}`).join('; ') }}
                  </p>
                </div>
                <div v-if="q.answer">
                  <p class="text-xs tracking-wider text-paper/50 uppercase">Respuesta del asistente</p>
                  <p class="mt-1 whitespace-pre-line text-paper/80">{{ q.answer }}</p>
                  <ul class="mt-2 list-disc space-y-0.5 pl-5 text-xs text-paper/70">
                    <li v-if="missingFacts(q).length">Faltan: {{ missingFacts(q).join(' · ') }}</li>
                    <li v-if="q.judge?.unsupported?.length">
                      Sin respaldo en el contexto: {{ q.judge.unsupported.join(' · ') }}
                    </li>
                    <li v-if="q.citations?.invalid?.length">
                      Artículos citados que no estaban en el contexto: {{ q.citations.invalid.join(', ') }}
                    </li>
                    <li v-if="q.abstained">El asistente se negó a responder.</li>
                  </ul>
                </div>
              </div>
            </li>
          </ul>
        </section>
      </template>
    </template>
  </div>
</template>
