<script setup>
import { ref, watch } from 'vue'
import L from 'leaflet'

// leaflet.markercluster depende del L global, no del módulo ESM importado
// directamente -- ver documentación de vue-leaflet-markercluster.
globalThis.L = L

import 'leaflet/dist/leaflet.css'
import 'vue-leaflet-markercluster/dist/style.css'
import { LMap, LTileLayer, LMarker, LPopup } from '@vue-leaflet/vue-leaflet'
import { LMarkerClusterGroup } from 'vue-leaflet-markercluster'
import { obtenerCompetidores } from '../services/api.js'

const props = defineProps({
  codiDistricte: { type: Number, required: true },
  nomDistricte: { type: String, default: '' },
})

// Centro de Barcelona como valor de respaldo, por si el distrito no tiene
// competidores cargados todavía (centro sería null).
const CENTRO_BARCELONA = [41.3851, 2.1734]

const cargando = ref(false)
const error = ref(null)
const centro = ref(CENTRO_BARCELONA)
const competidores = ref([])
const totalReal = ref(0)
const zoom = ref(14)
const mostrarCompetidores = ref(true)

async function cargarCompetidores() {
  cargando.value = true
  error.value = null
  try {
    const datos = await obtenerCompetidores(props.codiDistricte)
    centro.value = datos.centro ? [datos.centro.lat, datos.centro.lng] : CENTRO_BARCELONA
    competidores.value = datos.competidores
    totalReal.value = datos.total
  } catch (err) {
    error.value = 'No se pudieron cargar los competidores del distrito.'
  } finally {
    cargando.value = false
  }
}

watch(() => props.codiDistricte, cargarCompetidores, { immediate: true })

// Icono de cluster propio (latón/papel, acorde a la identidad visual),
// en vez del verde/amarillo/naranja por defecto del plugin.
function crearIconoCluster(cluster) {
  const cantidad = cluster.getChildCount()
  return L.divIcon({
    html: `<div style="background:#B8863D;color:#152238;border-radius:9999px;width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:600;font-family:'IBM Plex Mono',monospace;border:2px solid #F5F1E8;">${cantidad}</div>`,
    className: '',
    iconSize: [36, 36],
  })
}
</script>

<template>
  <div class="overflow-hidden rounded-lg border border-paper/15">
    <div class="flex items-center justify-between border-b border-paper/10 bg-ink-light px-4 py-2.5">
      <p class="text-xs tracking-wide text-paper/60 uppercase">
        {{ nomDistricte || 'Mapa del distrito' }}
        <span v-if="totalReal" class="text-paper/40">· {{ totalReal }} competidores en la base de datos</span>
      </p>
      <button
        @click="mostrarCompetidores = !mostrarCompetidores"
        class="rounded border border-brass/30 bg-brass/10 px-2.5 py-1 text-xs text-brass transition hover:bg-brass/20"
      >
        {{ mostrarCompetidores ? 'Ocultar competidores' : 'Mostrar competidores' }}
      </button>
    </div>

    <div v-if="error" class="bg-rojo/10 px-4 py-3 text-sm text-paper">{{ error }}</div>

    <div class="relative h-80 w-full">
      <div v-if="cargando" class="absolute inset-0 z-[1000] flex items-center justify-center bg-ink/60 text-sm text-paper/70">
        Cargando competidores…
      </div>
      <l-map :key="centro.join(',')" :zoom="zoom" :center="centro" :use-global-leaflet="true" class="h-full w-full">
        <l-tile-layer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="&copy; OpenStreetMap contributors"
        />
        <l-marker-cluster-group v-if="mostrarCompetidores" :icon-create-function="crearIconoCluster">
          <l-marker v-for="c in competidores" :key="c.id_global" :lat-lng="[c.lat, c.lng]">
            <l-popup><span class="text-sm">{{ c.nom_activitat }}</span></l-popup>
          </l-marker>
        </l-marker-cluster-group>
      </l-map>
    </div>

    <p v-if="totalReal > competidores.length" class="border-t border-paper/10 bg-ink-light px-4 py-2 text-xs text-paper/40">
      Mostrando {{ competidores.length }} de {{ totalReal }} competidores reales del distrito.
    </p>
  </div>
</template>