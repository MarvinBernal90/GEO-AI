<script setup>
import { computed, ref } from 'vue'
import FormularioViabilidad from './components/FormularioViabilidad.vue'
import TarjetaVeredicto from './components/TarjetaVeredicto.vue'
import BurbujaChat from './components/BurbujaChat.vue'
import MapaDistrito from './components/MapaDistrito.vue'
import { generarInformeStream } from './services/api.js'

const SEMAFOROS_VALIDOS = ['verde', 'ambar', 'rojo']

const cargando = ref(false)
const error = ref(null)
const codiDistrictePedido = ref(null)

const datosDistrito = ref(null)
const respuestaLegal = ref('')
const articulosCitados = ref([])
const textoSintesis = ref('')

// El semáforo es la primera línea del texto de síntesis -- se detecta en
// cuanto el streaming acumula un salto de línea, sin esperar a que
// termine el resumen completo. Así la tarjeta de veredicto aparece en
// cuanto se conoce el dato más importante, no al final de todo.
const semaforo = computed(() => {
  const primeraLinea = textoSintesis.value.split('\n')[0]?.trim().toLowerCase()
  return SEMAFOROS_VALIDOS.includes(primeraLinea) ? primeraLinea : null
})

const resumen = computed(() => {
  if (!semaforo.value) return ''
  return textoSintesis.value.split('\n').slice(1).join('\n').trim()
})

async function onGenerar({ codiDistricte, zonaPgm }) {
  cargando.value = true
  error.value = null
  codiDistrictePedido.value = codiDistricte
  datosDistrito.value = null
  respuestaLegal.value = ''
  articulosCitados.value = []
  textoSintesis.value = ''

  try {
    await generarInformeStream(codiDistricte, zonaPgm, {
      onDatos: (evento) => {
        datosDistrito.value = evento.datos_distrito
        respuestaLegal.value = evento.respuesta_legal
        articulosCitados.value = evento.articulos_citados
        cargando.value = false // ya hay algo que mostrar, aunque el veredicto siga en camino
      },
      onToken: (texto) => {
        textoSintesis.value += texto
      },
      onError: (detail) => {
        error.value = detail
      },
    })
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
        Consultando normativa y datos del distrito…
      </div>

      <div v-if="datosDistrito || respuestaLegal" class="space-y-5">
        <TarjetaVeredicto
          v-if="semaforo"
          :informe="{ semaforo, resumen, datos_distrito: datosDistrito || {} }"
        />
        <div v-else class="flex items-center gap-3 rounded-lg border border-paper/15 bg-paper px-6 py-5 text-sm text-ink/60">
          <span class="h-2 w-2 animate-ping rounded-full bg-brass" />
          Generando el veredicto…
        </div>

        <MapaDistrito
          v-if="datosDistrito"
          :codi-districte="codiDistrictePedido"
          :nom-districte="datosDistrito.nom_districte"
        />

        <BurbujaChat
          v-if="respuestaLegal"
          :informe="{ respuesta_legal: respuestaLegal, articulos_citados: articulosCitados }"
        />
      </div>
    </div>
  </div>
</template>