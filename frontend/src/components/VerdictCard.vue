<!--
==============================================================================
EXECUTIVE SUMMARY COMPONENT (STATELESS)
==============================================================================
File: frontend/src/components/VerdictCard.vue

A pure presentational "dumb" component. It receives the parsed LLM verdict
and district data via props, applying styling and formatting without holding
any business logic of its own. Dark card with a colored edge for the verdict.
-->
<script setup>
import { computed } from 'vue'

const props = defineProps({
  informe: { type: Object, required: true },
})

// Data Dictionary mapping LLM string literals to UI tokens
const COLORES = {
  rojo: {
    bg: 'bg-rojo',
    glow: 'shadow-[0_0_12px_2px] shadow-rojo/50',
    borde: 'border-l-rojo',
    texto: 'Riesgo alto',
    textoClase: 'text-rojo',
  },
  ambar: {
    bg: 'bg-ambar',
    glow: 'shadow-[0_0_12px_2px] shadow-ambar/50',
    borde: 'border-l-ambar',
    texto: 'Viable con reservas',
    textoClase: 'text-ambar',
  },
  verde: {
    bg: 'bg-verde',
    glow: 'shadow-[0_0_12px_2px] shadow-verde/50',
    borde: 'border-l-verde',
    texto: 'Condiciones favorables',
    textoClase: 'text-verde',
  },
}

// Graceful Degradation: If the LLM output is malformed, default to Amber (Warning)
const claveActiva = computed(() => (Object.hasOwn(COLORES, props.informe.semaforo) ? props.informe.semaforo : 'ambar'))
const veredicto = computed(() => COLORES[claveActiva.value])

// Native Browser i18n (Internationalization) for strict Spanish formatting
const formatoNumero = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0 })
const formatoMoneda = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })
const formatoPorcentaje = new Intl.NumberFormat('es-ES', {
  style: 'percent',
  maximumFractionDigits: 1,
  signDisplay: 'exceptZero',
})

const datos = computed(() => props.informe.datos_distrito ?? {})

// `daily_foot_traffic` is an index, not a head count: (residents + people who
// arrive - people who leave) / residents. A value of 1.04 means 4% more people
// than residents on an average day. We show it as a signed percentage.
// A value of 0 means the district has no population data, so we show a dash.
const afluencia = computed(() => {
  const indice = Number(datos.value.daily_foot_traffic)
  if (!Number.isFinite(indice) || indice <= 0) return '—'
  return formatoPorcentaje.format(indice - 1)
})
</script>

<template>
  <article
    class="overflow-hidden rounded-xl border border-l-4 border-paper/10 bg-ink-light text-paper"
    :class="veredicto.borde"
  >
    <!-- Cabecera de expediente -->
    <div class="flex items-start justify-between gap-4 px-5 pt-4">
      <div>
        <p class="font-mono text-[10px] tracking-[0.2em] text-paper/45 uppercase">Expediente de viabilidad</p>
        <h2 class="font-display text-2xl font-semibold">
          {{ datos.nom_districte ?? 'Distrito sin datos' }}
        </h2>
        <p class="mt-1 text-xs font-medium tracking-wide uppercase" :class="veredicto.textoClase">
          {{ veredicto.texto }}
        </p>
      </div>

      <!-- Semáforo vertical: solo la luz del veredicto encendida -->
      <div
        class="flex flex-col items-center gap-1.5 rounded-full border border-paper/10 bg-ink px-2 py-2.5"
        aria-hidden="true"
      >
        <span
          v-for="color in ['rojo', 'ambar', 'verde']"
          :key="color"
          class="h-3 w-3 rounded-full transition"
          :class="color === claveActiva ? [COLORES[color].bg, COLORES[color].glow] : 'bg-paper/10'"
        />
      </div>
    </div>

    <!-- Veredicto en prosa -->
    <p class="px-5 py-4 text-sm leading-relaxed text-paper/85">{{ informe.resumen }}</p>

    <!-- Ficha de datos: celdas separadas por líneas finas -->
    <dl class="grid grid-cols-2 gap-px border-t border-paper/10 bg-paper/10 sm:grid-cols-3">
      <div class="bg-ink-light px-5 py-3">
        <dt class="text-[10px] tracking-wide text-paper/45 uppercase">Renta media</dt>
        <dd class="mt-0.5 font-mono text-sm font-medium">
          {{ datos.renta_media != null ? formatoMoneda.format(datos.renta_media) : '—' }}
        </dd>
      </div>
      <div class="bg-ink-light px-5 py-3">
        <dt
          class="text-[10px] tracking-wide text-paper/45 uppercase"
          title="Personas presentes en un día medio respecto a los residentes del distrito"
        >
          Afluencia vs. residentes
        </dt>
        <dd class="mt-0.5 font-mono text-sm font-medium">{{ afluencia }}</dd>
      </div>
      <div class="bg-ink-light px-5 py-3">
        <dt class="text-[10px] tracking-wide text-paper/45 uppercase">Competidores en el distrito</dt>
        <dd class="mt-0.5 font-mono text-sm font-medium">
          {{ datos.total_competitors != null ? formatoNumero.format(datos.total_competitors) : '—' }}
        </dd>
      </div>
      <div class="bg-ink-light px-5 py-3">
        <dt class="text-[10px] tracking-wide text-paper/45 uppercase">Índice de oportunidad</dt>
        <dd class="mt-0.5 font-mono text-sm font-medium">
          {{ datos.opportunity_score != null ? `${datos.opportunity_score} / 100` : '—' }}
        </dd>
      </div>
      <div class="bg-ink-light px-5 py-3">
        <dt
          class="text-[10px] tracking-wide text-paper/45 uppercase"
          title="Personas que hay en el distrito un día medio: residentes, más las que llegan, menos las que salen"
        >
          Población flotante
        </dt>
        <dd class="mt-0.5 font-mono text-sm font-medium">
          {{ datos.viajes_intraprovinciales != null ? formatoNumero.format(datos.viajes_intraprovinciales) : '—' }}
        </dd>
      </div>
      <div class="bg-ink-light px-5 py-3">
        <dt class="text-[10px] tracking-wide text-paper/45 uppercase">Edad predominante</dt>
        <dd class="mt-0.5 font-mono text-sm font-medium">
          {{ datos.predominant_age || '—' }}
        </dd>
      </div>
    </dl>
  </article>
</template>
