<script setup>
import { ref } from 'vue'
import FormularioViabilidad from './components/FormularioViabilidad.vue'
import TarjetaVeredicto from './components/TarjetaVeredicto.vue'
import BurbujaChat from './components/BurbujaChat.vue'
import MapaDistrito from './components/MapaDistrito.vue'
import { generarInforme } from './services/api.js'

const cargando = ref(false)
const error = ref(null)
const informe = ref(null)
const codiDistrictePedido = ref(null)

async function onGenerar({ codiDistricte, zonaPgm }) {
  cargando.value = true
  error.value = null
  informe.value = null
  codiDistrictePedido.value = codiDistricte
  try {
    informe.value = await generarInforme(codiDistricte, zonaPgm)
  } catch (err) {
    error.value = err.message
  } finally {
    cargando.value = false
  }
}
</script>

<template>
  <div class="fondo-plano min-h-screen">
    <div class="mx-auto max-w-3xl px-4 py-12 sm:py-16">
      <header class="mb-10">
        <p class="mb-2 font-mono text-xs tracking-[0.2em] text-brass uppercase">Geo-Yield-AI</p>
        <h1 class="font-display text-3xl font-semibold text-paper sm:text-4xl">
          Dossier de viabilidad de hostelería
        </h1>
        <p class="mt-2 max-w-xl text-sm text-paper/60">
          Selecciona un distrito y una zona urbanística de Barcelona para generar un informe
          que cruza normativa legal vigente con datos socioeconómicos reales.
        </p>
      </header>

      <div class="mb-8 rounded-lg border border-paper/15 bg-ink-light/40 p-6">
        <FormularioViabilidad :cargando="cargando" @generar="onGenerar" />
      </div>

      <div v-if="error" class="mb-8 rounded border border-rojo/40 bg-rojo/10 px-4 py-3 text-sm text-paper">
        {{ error }}
      </div>

      <div v-if="cargando" class="flex items-center gap-3 text-sm text-paper/50">
        <span class="h-2 w-2 animate-ping rounded-full bg-brass" />
        Consultando normativa y generando el informe…
      </div>

      <div v-if="informe" class="space-y-5">
        <TarjetaVeredicto :informe="informe" />
        <MapaDistrito
          :codi-districte="codiDistrictePedido"
          :nom-districte="informe.datos_distrito?.nom_districte"
        />
        <BurbujaChat :informe="informe" />
      </div>
    </div>
  </div>
</template>
