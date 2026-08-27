<script setup>
import { onMounted, ref } from 'vue'
import { obtenerDistritos, obtenerZonasPgm } from '../services/api.js'

const emit = defineEmits(['generar'])
defineProps({ cargando: { type: Boolean, default: false } })

const distritos = ref([])
const zonas = ref([])
const codiDistricte = ref(null)
const zonaPgm = ref(null)
const errorCarga = ref(null)

onMounted(async () => {
  try {
    const [listaDistritos, listaZonas] = await Promise.all([obtenerDistritos(), obtenerZonasPgm()])
    distritos.value = listaDistritos
    zonas.value = listaZonas
  } catch (err) {
    errorCarga.value = 'No se pudieron cargar los distritos y zonas. Comprueba que la API esté arrancada.'
  }
})

function onSubmit() {
  if (codiDistricte.value && zonaPgm.value) {
    emit('generar', { codiDistricte: codiDistricte.value, zonaPgm: zonaPgm.value })
  }
}
</script>

<template>
  <form @submit.prevent="onSubmit" class="space-y-5">
    <div v-if="errorCarga" class="rounded border border-rojo/40 bg-rojo/10 px-4 py-3 text-sm text-paper">
      {{ errorCarga }}
    </div>

    <div>
      <label for="distrito" class="mb-1.5 block text-xs font-medium tracking-wide text-paper/60 uppercase">
        Distrito
      </label>
      <select
        id="distrito"
        v-model="codiDistricte"
        required
        class="w-full rounded border border-paper/20 bg-ink-light px-3 py-2.5 text-paper focus:border-brass focus:ring-1 focus:ring-brass focus:outline-none"
      >
        <option :value="null" disabled>Selecciona un distrito</option>
        <option v-for="d in distritos" :key="d.codi_districte" :value="d.codi_districte">
          {{ d.nom_districte }}
        </option>
      </select>
    </div>

    <div>
      <label for="zona" class="mb-1.5 block text-xs font-medium tracking-wide text-paper/60 uppercase">
        Zona urbanística (PGM)
      </label>
      <select
        id="zona"
        v-model="zonaPgm"
        required
        class="w-full rounded border border-paper/20 bg-ink-light px-3 py-2.5 text-paper focus:border-brass focus:ring-1 focus:ring-brass focus:outline-none"
      >
        <option :value="null" disabled>Selecciona una zona</option>
        <option v-for="z in zonas" :key="z.id" :value="z.id">{{ z.nombre }}</option>
      </select>
      <p class="mt-1.5 text-xs text-paper/40">
        Un distrito puede abarcar varias zonas PGM -- indícala tú si la conoces.
      </p>
    </div>

    <button
      type="submit"
      :disabled="cargando || !codiDistricte || !zonaPgm"
      class="w-full rounded bg-brass px-4 py-2.5 font-medium text-ink transition hover:bg-brass/90 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {{ cargando ? 'Generando informe…' : 'Generar informe de viabilidad' }}
    </button>
  </form>
</template>
