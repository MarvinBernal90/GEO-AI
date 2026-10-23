<!--
==============================================================================
ECHART WRAPPER
==============================================================================
File: frontend/src/components/metrics/EChart.vue

Thin Vue wrapper around Apache ECharts. Only the chart types and components the
dashboard uses are registered, so the bundle stays small. It resizes with its
container, redraws when `option` changes and disposes the instance on unmount.
-->
<script setup>
import { BarChart, LineChart } from 'echarts/charts'
import { AriaComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, shallowRef, toRaw, watch } from 'vue'

echarts.use([BarChart, LineChart, AriaComponent, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: String, default: '260px' },
  // Read by screen readers; the table view of the card has the actual numbers.
  label: { type: String, default: '' },
})

const root = shallowRef(null)
let chart = null
let observer = null

function draw() {
  // notMerge: a series that disappears (a filter) must disappear from the canvas too.
  chart?.setOption(toRaw(props.option), { notMerge: true })
}

onMounted(() => {
  chart = echarts.init(root.value, null, { renderer: 'canvas' })
  draw()
  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(root.value)
})

watch(() => props.option, draw)

onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="root" role="img" :aria-label="label" :style="{ height }" class="w-full" />
</template>
