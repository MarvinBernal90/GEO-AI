<!--
==============================================================================
KPI CARD (STAT TILE)
==============================================================================
File: frontend/src/components/metrics/KpiCard.vue

One headline number with an optional hint and a 2 px sparkline. `tone` colors
only the small marker, never the number: "critical" always carries its own
word in the hint, so state is never color alone.
-->
<script setup>
import { computed } from 'vue'

import { INK, SERIES, STATUS } from '../../utils/chartTheme.js'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: String, required: true },
  hint: { type: String, default: '' },
  // Numbers for the sparkline (oldest first). Hidden when fewer than 2 points.
  trend: { type: Array, default: () => [] },
  tone: { type: String, default: 'default' }, // default | good | critical
  color: { type: String, default: SERIES[0] },
})

const W = 96
const H = 28
const PAD = 4

const spark = computed(() => {
  const values = props.trend.filter((v) => typeof v === 'number' && Number.isFinite(v))
  if (values.length < 2) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const points = values.map((v, i) => [
    PAD + (i / (values.length - 1)) * (W - PAD * 2),
    H - PAD - ((v - min) / span) * (H - PAD * 2),
  ])
  const last = points[points.length - 1]
  return { line: points.map((p) => p.join(',')).join(' '), last }
})

const marker = computed(() => ({ good: STATUS.ok, critical: STATUS.error })[props.tone] ?? null)
</script>

<template>
  <div class="flex min-w-0 flex-col justify-between rounded-xl border border-paper/15 bg-ink-light/50 p-4 shadow-lg">
    <div class="flex items-center gap-2">
      <span
        v-if="marker"
        class="h-2 w-2 shrink-0 rounded-full"
        :style="{ backgroundColor: marker }"
        aria-hidden="true"
      />
      <p class="truncate text-xs text-paper/60">{{ label }}</p>
    </div>

    <div class="mt-2 flex items-end justify-between gap-3">
      <p class="truncate text-2xl leading-none font-semibold text-paper" :title="value">{{ value }}</p>
      <svg v-if="spark" :width="W" :height="H" :viewBox="`0 0 ${W} ${H}`" class="shrink-0" aria-hidden="true">
        <polyline
          :points="spark.line"
          fill="none"
          :stroke="color"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
        <circle :cx="spark.last[0]" :cy="spark.last[1]" r="4" :fill="color" :stroke="INK.surface" stroke-width="2" />
      </svg>
    </div>

    <p class="mt-2 min-h-4 truncate text-[11px] text-paper/50" :title="hint">{{ hint }}</p>
  </div>
</template>
