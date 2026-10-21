<!--
==============================================================================
GEOSPATIAL VISUALIZATION COMPONENT (MAPLIBRE, DARK)
==============================================================================
File: frontend/src/components/DistrictMap.vue

Dark map that fills the height of its parent. It follows the last report:
- no district      -> the whole city of Barcelona,
- district only    -> flies to the district and plots its competitors,
- exact location   -> flies to the point, draws rings of 100/200/400 m and
                      plots the competitors around it.
Clicking a cluster highlights the competitors inside it (amber) and frames them.
When zoomed in, it also shows the activity next to each competitor and, if the
basemap tiles have them, shop names and house numbers. Basemap labels (streets,
places) are restyled for contrast on the dark background.

MapLibre GL is loaded on demand (a separate chunk). Basemap: CARTO Dark Matter
(free, attribution required; review its terms before commercial use).
-->
<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { obtenerCompetidores } from '../services/api.js'
import { createLogger } from '../services/logger.js'

const log = createLogger('component.mapa')

const props = defineProps({
  // Without a district the map shows the whole city.
  codiDistricte: { type: Number, default: null },
  nomDistricte: { type: String, default: '' },
  // If provided, triggers a 'Radius Search' instead of a 'District Search'
  ubicacion: { type: Object, default: null }, // { lat, lon } | null
})

const STYLE_URL = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
const CITY_BOUNDS = [
  [2.05, 41.31],
  [2.23, 41.47],
]
const RINGS_M = [100, 200, 400]
const COLOR_COMPETIDOR = '#ff6f7d'
const COLOR_ANILLO = '#8ab0ff'
const COLOR_ACENTO = '#5b8cff'
const COLOR_SELECCION = '#f5b942'
const COLOR_FONDO = '#0b0e14'

const SRC_COMPETIDORES = 'competidores'
const SRC_ANILLOS = 'anillos'
const SRC_UBICACION = 'ubicacion'
const SRC_SELECCION = 'seleccion'
const CAPAS_COMPETIDORES = [
  'competidores-cluster-halo',
  'competidores-cluster',
  'competidores-cuenta',
  'competidores-halo',
  'competidores-punto',
  'competidores-etiqueta',
  'seleccion-halo',
  'seleccion-punto',
  'seleccion-etiqueta',
]
const EMPTY = { type: 'FeatureCollection', features: [] }

const contenedor = ref(null)
const listo = ref(false)
const cargando = ref(false)
const error = ref(null)
const totalReal = ref(0)
const mostradas = ref(0)
const modo = ref('distrito') // 'distrito' | 'radio'
const radioMetros = ref(null)
const mostrarCompetidores = ref(true)
const seleccionados = ref(0) // competitors highlighted from a clicked cluster

let map = null
let maplibregl = null
let resizeObserver = null
let peticion = 0 // id of the latest request, so stale answers are ignored

// ---------------------------------------------------------------------------
// GEOMETRY HELPERS
// ---------------------------------------------------------------------------

/** A circle of `metres` around a point, as a polygon feature (64 sides). */
function circulo(lon, lat, metres, steps = 64) {
  const dLat = metres / 111320
  const dLon = metres / (111320 * Math.cos((lat * Math.PI) / 180))
  const ring = []
  for (let i = 0; i <= steps; i++) {
    const angle = (i / steps) * 2 * Math.PI
    ring.push([lon + dLon * Math.cos(angle), lat + dLat * Math.sin(angle)])
  }
  return { type: 'Feature', properties: { radio: metres }, geometry: { type: 'Polygon', coordinates: [ring] } }
}

/** Bounding box [[west, south], [east, north]] of a circle around a point. */
function limitesCirculo(lon, lat, metres) {
  const dLat = metres / 111320
  const dLon = metres / (111320 * Math.cos((lat * Math.PI) / 180))
  return [
    [lon - dLon, lat - dLat],
    [lon + dLon, lat + dLat],
  ]
}

/** Bounding box [[west, south], [east, north]] of a list of point features. */
function limitesPuntos(features) {
  const lons = features.map((f) => f.geometry.coordinates[0])
  const lats = features.map((f) => f.geometry.coordinates[1])
  return [
    [Math.min(...lons), Math.min(...lats)],
    [Math.max(...lons), Math.max(...lats)],
  ]
}

function puntosGeoJSON(competidores) {
  return {
    type: 'FeatureCollection',
    features: competidores.map((c) => ({
      type: 'Feature',
      properties: { nombre: c.nom_activitat },
      geometry: { type: 'Point', coordinates: [c.lng, c.lat] },
    })),
  }
}

/**
 * Font stack used by the basemap labels. Our own labels reuse it, so the
 * glyphs they need are served by the same style. Italic stacks (parks, water)
 * are skipped: the first symbol layer of the style happens to be one of them.
 */
function fuenteDelEstilo() {
  const OPERADORES = ['literal', 'get', 'match', 'case', 'step', 'interpolate', 'coalesce']
  const resolver = (font) => {
    if (!Array.isArray(font)) return null
    if (font[0] === 'literal' && Array.isArray(font[1])) return font[1]
    if (font.every((f) => typeof f === 'string') && !OPERADORES.includes(font[0])) return font
    return null
  }
  const fuentes = map
    .getStyle()
    .layers.filter((l) => l.type === 'symbol' && l.layout?.['text-font'])
    .map((l) => resolver(l.layout['text-font']))
    .filter(Boolean)
  return fuentes.find((f) => !f.some((nombre) => /italic/i.test(nombre))) ?? fuentes[0] ?? ['Open Sans Regular']
}

// ---------------------------------------------------------------------------
// MAP LAYERS
// ---------------------------------------------------------------------------

/**
 * Makes the basemap labels easier to read on the dark background: brighter text,
 * a dark halo, and bigger street names that appear earlier. It runs before our own
 * layers are added, so it only touches the basemap.
 */
function mejorarEtiquetasDelMapa() {
  const capas = map.getStyle().layers.filter((l) => l.type === 'symbol' && l.layout?.['text-field'])
  let calles = 0
  for (const capa of capas) {
    const esCalle = capa['source-layer'] === 'transportation_name' || /road|street|highway/i.test(capa.id)
    const esPortal = capa['source-layer'] === 'housenumber' || /house/i.test(capa.id)
    try {
      map.setPaintProperty(capa.id, 'text-color', esCalle ? '#dfe5f2' : esPortal ? '#6f7a92' : '#c3cad9')
      map.setPaintProperty(capa.id, 'text-halo-color', COLOR_FONDO)
      map.setPaintProperty(capa.id, 'text-halo-width', 1.6)
      if (esCalle) {
        map.setLayoutProperty(capa.id, 'text-size', ['interpolate', ['linear'], ['zoom'], 13, 10, 17, 13, 19, 15])
        map.setLayerZoomRange(capa.id, Math.min(capa.minzoom ?? 14, 14), capa.maxzoom ?? 24)
        calles++
      }
    } catch (err) {
      log.warn('Could not restyle a basemap label layer', { error: err, layer: capa.id })
    }
  }
  log.event('mapa.etiquetas', {
    capas_texto: capas.length,
    capas_calle: calles,
    origenes: [...new Set(capas.map((l) => l['source-layer']).filter(Boolean))].join(', '),
  })
}

/**
 * Adds house numbers and shop/restaurant names from the basemap's own vector
 * tiles (OpenStreetMap data). It only adds a layer if the tiles really contain
 * it, so a different basemap never breaks the map.
 */
function anadirDetalleDelMapa(fuente) {
  const [idFuente] = Object.entries(map.getStyle().sources ?? {}).find(([, s]) => s.type === 'vector') ?? []
  if (!idFuente) return
  const capas = map.getSource(idFuente)?.vectorLayerIds ?? []
  log.event('mapa.capas_base', { has_poi: capas.includes('poi'), has_housenumber: capas.includes('housenumber') })

  if (capas.includes('housenumber')) {
    map.addLayer({
      id: 'detalle-portales',
      type: 'symbol',
      source: idFuente,
      'source-layer': 'housenumber',
      minzoom: 17,
      layout: { 'text-field': ['get', 'housenumber'], 'text-font': fuente, 'text-size': 10 },
      paint: { 'text-color': '#7f8aa3', 'text-halo-color': COLOR_FONDO, 'text-halo-width': 1 },
    })
  }
  if (capas.includes('poi')) {
    map.addLayer({
      id: 'detalle-locales',
      type: 'symbol',
      source: idFuente,
      'source-layer': 'poi',
      minzoom: 16,
      filter: ['has', 'name'],
      layout: {
        'text-field': ['get', 'name'],
        'text-font': fuente,
        'text-size': 11,
        'text-anchor': 'top',
        'text-offset': [0, 0.5],
        'text-max-width': 8,
      },
      paint: { 'text-color': '#aab4c8', 'text-halo-color': COLOR_FONDO, 'text-halo-width': 1.2 },
    })
  }
}

function anadirCapas() {
  const fuente = fuenteDelEstilo()

  map.addSource(SRC_COMPETIDORES, {
    type: 'geojson',
    data: EMPTY,
    cluster: true,
    clusterMaxZoom: 15,
    clusterRadius: 48,
  })
  map.addSource(SRC_ANILLOS, { type: 'geojson', data: EMPTY })
  map.addSource(SRC_UBICACION, { type: 'geojson', data: EMPTY })
  map.addSource(SRC_SELECCION, { type: 'geojson', data: EMPTY })

  map.addLayer({
    id: 'anillos-relleno',
    type: 'fill',
    source: SRC_ANILLOS,
    paint: { 'fill-color': COLOR_ANILLO, 'fill-opacity': 0.04 },
  })
  map.addLayer({
    id: 'anillos-linea',
    type: 'line',
    source: SRC_ANILLOS,
    paint: { 'line-color': COLOR_ANILLO, 'line-width': 1.5, 'line-dasharray': [2, 2], 'line-opacity': 0.8 },
  })

  anadirDetalleDelMapa(fuente)

  // Clusters: translucent fill + thin ring + soft glow, with a white counter.
  map.addLayer({
    id: 'competidores-cluster-halo',
    type: 'circle',
    source: SRC_COMPETIDORES,
    filter: ['has', 'point_count'],
    paint: {
      'circle-color': COLOR_COMPETIDOR,
      'circle-opacity': 0.14,
      'circle-blur': 0.8,
      'circle-radius': ['step', ['get', 'point_count'], 22, 10, 27, 50, 34],
    },
  })
  map.addLayer({
    id: 'competidores-cluster',
    type: 'circle',
    source: SRC_COMPETIDORES,
    filter: ['has', 'point_count'],
    paint: {
      'circle-color': 'rgba(255, 111, 125, 0.28)',
      'circle-radius': ['step', ['get', 'point_count'], 15, 10, 19, 50, 25],
      'circle-stroke-width': 1.5,
      'circle-stroke-color': COLOR_COMPETIDOR,
    },
  })
  map.addLayer({
    id: 'competidores-cuenta',
    type: 'symbol',
    source: SRC_COMPETIDORES,
    filter: ['has', 'point_count'],
    layout: {
      'text-field': ['get', 'point_count_abbreviated'],
      'text-font': fuente,
      'text-size': 12,
      'text-allow-overlap': true,
      'text-ignore-placement': true,
    },
    paint: { 'text-color': '#ffffff' },
  })

  // Single competitors: a dot with a soft glow that grows with the zoom.
  map.addLayer({
    id: 'competidores-halo',
    type: 'circle',
    source: SRC_COMPETIDORES,
    filter: ['!', ['has', 'point_count']],
    paint: {
      'circle-color': COLOR_COMPETIDOR,
      'circle-opacity': 0.18,
      'circle-blur': 0.6,
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 14, 7, 18, 13],
    },
  })
  map.addLayer({
    id: 'competidores-punto',
    type: 'circle',
    source: SRC_COMPETIDORES,
    filter: ['!', ['has', 'point_count']],
    paint: {
      'circle-color': COLOR_COMPETIDOR,
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 14, 3.5, 17, 5, 19, 7],
      'circle-stroke-width': 1,
      'circle-stroke-color': 'rgba(255, 255, 255, 0.6)',
    },
  })
  // The activity of each competitor, only when zoomed in enough to read it.
  map.addLayer({
    id: 'competidores-etiqueta',
    type: 'symbol',
    source: SRC_COMPETIDORES,
    filter: ['!', ['has', 'point_count']],
    minzoom: 16.5,
    layout: {
      'text-field': ['get', 'nombre'],
      'text-font': fuente,
      'text-size': 11,
      'text-anchor': 'top',
      'text-offset': [0, 0.9],
      'text-optional': true,
      'text-max-width': 8,
    },
    paint: { 'text-color': '#ffb3bc', 'text-halo-color': COLOR_FONDO, 'text-halo-width': 1.5 },
  })

  // Competitors of the clicked cluster: amber, on top of everything else.
  map.addLayer({
    id: 'seleccion-halo',
    type: 'circle',
    source: SRC_SELECCION,
    paint: {
      'circle-color': COLOR_SELECCION,
      'circle-opacity': 0.22,
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 13, 12, 18, 20],
    },
  })
  map.addLayer({
    id: 'seleccion-punto',
    type: 'circle',
    source: SRC_SELECCION,
    paint: {
      'circle-color': COLOR_SELECCION,
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 13, 5, 18, 8],
      'circle-stroke-width': 2,
      'circle-stroke-color': '#ffffff',
    },
  })
  map.addLayer({
    id: 'seleccion-etiqueta',
    type: 'symbol',
    source: SRC_SELECCION,
    layout: {
      'text-field': ['get', 'nombre'],
      'text-font': fuente,
      'text-size': 12,
      'text-anchor': 'top',
      'text-offset': [0, 1.2],
      'text-optional': true,
      'text-max-width': 9,
    },
    paint: { 'text-color': COLOR_SELECCION, 'text-halo-color': COLOR_FONDO, 'text-halo-width': 1.5 },
  })

  map.addLayer({
    id: 'ubicacion-halo',
    type: 'circle',
    source: SRC_UBICACION,
    paint: { 'circle-radius': 16, 'circle-color': COLOR_ACENTO, 'circle-opacity': 0.25 },
  })
  map.addLayer({
    id: 'ubicacion-punto',
    type: 'circle',
    source: SRC_UBICACION,
    paint: {
      'circle-radius': 7,
      'circle-color': '#ffffff',
      'circle-stroke-width': 3,
      'circle-stroke-color': COLOR_ACENTO,
    },
  })

  // Click a cluster: highlight the competitors inside it and frame them.
  map.on('click', 'competidores-cluster', async (e) => {
    const feature = map.queryRenderedFeatures(e.point, { layers: ['competidores-cluster'] })[0]
    if (!feature) return
    try {
      const { cluster_id: id, point_count: total } = feature.properties
      const hojas = await map.getSource(SRC_COMPETIDORES).getClusterLeaves(id, total, 0)
      if (!hojas.length) return
      resaltar(hojas)
      map.fitBounds(limitesPuntos(hojas), { padding: 100, maxZoom: 17.5, duration: 900 })
    } catch (err) {
      log.warn('Could not open the cluster', { error: err })
    }
  })

  // Click on empty map: clear the highlight.
  map.on('click', (e) => {
    const sobre = map.queryRenderedFeatures(e.point, {
      layers: ['competidores-cluster', 'competidores-punto', 'seleccion-punto'],
    })
    if (!sobre.length) limpiarSeleccion()
  })

  // Click a competitor: show its activity. setText avoids injecting HTML.
  map.on('click', 'competidores-punto', (e) => {
    const feature = e.features?.[0]
    if (!feature) return
    new maplibregl.Popup({ closeButton: false, offset: 10, maxWidth: '240px' })
      .setLngLat(feature.geometry.coordinates)
      .setText(feature.properties.nombre)
      .addTo(map)
  })

  for (const capa of ['competidores-cluster', 'competidores-punto']) {
    map.on('mouseenter', capa, () => (map.getCanvas().style.cursor = 'pointer'))
    map.on('mouseleave', capa, () => (map.getCanvas().style.cursor = ''))
  }
}

/** Highlights the given point features (the leaves of a cluster). */
function resaltar(hojas) {
  map.getSource(SRC_SELECCION).setData({
    type: 'FeatureCollection',
    features: hojas.map((h) => ({
      type: 'Feature',
      properties: { nombre: h.properties.nombre },
      geometry: h.geometry,
    })),
  })
  seleccionados.value = hojas.length
}

function limpiarSeleccion() {
  if (map?.getSource(SRC_SELECCION)) map.getSource(SRC_SELECCION).setData(EMPTY)
  seleccionados.value = 0
}

function irACiudad() {
  map.fitBounds(CITY_BOUNDS, { padding: 40, duration: 1000 })
}

function vaciarCapas() {
  map.getSource(SRC_COMPETIDORES).setData(EMPTY)
  map.getSource(SRC_ANILLOS).setData(EMPTY)
  map.getSource(SRC_UBICACION).setData(EMPTY)
  limpiarSeleccion()
}

/** Draws the answer of the competitors endpoint and moves the camera. */
function pintar(datos) {
  limpiarSeleccion()
  const lista = datos.competidores ?? []
  map.getSource(SRC_COMPETIDORES).setData(puntosGeoJSON(lista))

  const punto = datos.modo === 'radio' ? datos.centro : null
  if (punto) {
    map.getSource(SRC_ANILLOS).setData({
      type: 'FeatureCollection',
      features: RINGS_M.map((metros) => circulo(punto.lng, punto.lat, metros)),
    })
    map.getSource(SRC_UBICACION).setData({
      type: 'FeatureCollection',
      features: [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [punto.lng, punto.lat] } }],
    })
    map.fitBounds(limitesCirculo(punto.lng, punto.lat, 450), { padding: 60, maxZoom: 17, duration: 1400 })
    return
  }

  map.getSource(SRC_ANILLOS).setData(EMPTY)
  map.getSource(SRC_UBICACION).setData(EMPTY)
  if (datos.centro) map.flyTo({ center: [datos.centro.lng, datos.centro.lat], zoom: 13.5, duration: 1400 })
  else irACiudad()
}

// ---------------------------------------------------------------------------
// DATA LOADING
// ---------------------------------------------------------------------------

async function actualizar() {
  if (!listo.value) return
  const id = ++peticion

  if (!props.codiDistricte) {
    error.value = null
    cargando.value = false
    totalReal.value = 0
    mostradas.value = 0
    modo.value = 'distrito'
    radioMetros.value = null
    vaciarCapas()
    irACiudad()
    return
  }

  cargando.value = true
  error.value = null
  try {
    const datos = await obtenerCompetidores(props.codiDistricte, props.ubicacion)
    if (id !== peticion) return // a newer request replaced this one

    totalReal.value = datos.total
    mostradas.value = datos.competidores?.length ?? 0
    modo.value = datos.modo
    radioMetros.value = datos.radio_metros
    pintar(datos)

    log.event('competidores.consultados', {
      codi_districte: props.codiDistricte,
      modo: datos.modo,
      total: datos.total,
      radio_metros: datos.radio_metros,
    })
  } catch (err) {
    if (id !== peticion) return
    log.error('Could not load competitors', {
      error: err,
      codi_districte: props.codiDistricte,
      by_radius: props.ubicacion !== null,
    })
    error.value = 'No se pudieron cargar los competidores del distrito.'
  } finally {
    if (id === peticion) cargando.value = false
  }
}

// Reactively reload data if the district OR the specific address changes
watch(() => [props.codiDistricte, props.ubicacion], actualizar, { deep: true })

watch(mostrarCompetidores, (visible) => {
  if (!listo.value) return
  for (const capa of CAPAS_COMPETIDORES) {
    map.setLayoutProperty(capa, 'visibility', visible ? 'visible' : 'none')
  }
})

// ---------------------------------------------------------------------------
// LIFECYCLE
// ---------------------------------------------------------------------------

onMounted(async () => {
  try {
    // MapLibre 6 is ESM only and has no default export. With a bundler the worker
    // URL must be given once, so Vite can resolve it in dev and in production.
    const [modulo, worker] = await Promise.all([
      import('maplibre-gl'),
      import('maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'),
      import('maplibre-gl/dist/maplibre-gl.css'),
    ])
    // Depending on how the bundler wraps the package, the API is on `default` or on the module itself.
    maplibregl = modulo.default ?? modulo
    maplibregl.setWorkerUrl(worker.default)

    map = new maplibregl.Map({
      container: contenedor.value,
      style: STYLE_URL,
      bounds: CITY_BOUNDS,
      fitBoundsOptions: { padding: 40 },
      attributionControl: { compact: true },
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')

    const cargado = new Promise((resolve) => map.once('load', resolve))
    map.on('error', (e) => {
      log.warn('Map error', { error: e?.error })
      if (!listo.value) {
        error.value = 'No se pudo cargar el mapa. Recarga la página; si sigue fallando, revisa tu conexión.'
      }
    })
    await cargado

    error.value = null
    mejorarEtiquetasDelMapa()
    anadirCapas()
    resizeObserver = new ResizeObserver(() => map?.resize())
    resizeObserver.observe(contenedor.value)
    listo.value = true
    await actualizar()
  } catch (err) {
    log.error('Could not start the map', { error: err })
    // Only blame WebGL when MapLibre says so (its own error type, if this version has it).
    const sinWebGL =
      typeof maplibregl?.GPUInitializationError === 'function' && err instanceof maplibregl.GPUInitializationError
    error.value = sinWebGL
      ? 'Tu navegador no puede mostrar el mapa porque no tiene WebGL2 activado.'
      : 'No se pudo iniciar el mapa. Recarga la página e inténtalo de nuevo.'
  }
})

onBeforeUnmount(() => {
  peticion++ // ignore any answer still in flight
  resizeObserver?.disconnect()
  map?.remove()
  map = null
})

const resumenMapa = computed(() => {
  if (!props.codiDistricte || !totalReal.value) return ''
  const base =
    modo.value === 'radio'
      ? `${totalReal.value} competidores en un radio de ${radioMetros.value} m · anillos de 100, 200 y 400 m`
      : `${totalReal.value} competidores registrados en el distrito`
  return mostradas.value < totalReal.value ? `${base} (se muestran ${mostradas.value})` : base
})
</script>

<template>
  <div class="relative h-full min-h-[320px] overflow-hidden bg-ink">
    <!-- MapLibre forces its own container to position: relative, so the size comes from this wrapper -->
    <div class="absolute inset-0">
      <div ref="contenedor" class="h-full w-full" role="region" aria-label="Mapa de Barcelona" />
    </div>

    <!-- Title and counters -->
    <div
      class="pointer-events-none absolute top-3 left-3 z-10 max-w-[65%] rounded-lg border border-paper/10 bg-ink/90 px-3 py-2"
    >
      <p class="text-xs font-medium tracking-wide text-paper uppercase">
        {{ nomDistricte || 'Barcelona y sus diez distritos' }}
      </p>
      <p v-if="resumenMapa" class="mt-0.5 text-[11px] text-paper/60">{{ resumenMapa }}</p>
    </div>

    <button
      v-if="codiDistricte && listo"
      type="button"
      class="absolute top-3 right-14 z-10 rounded-lg border border-paper/10 bg-ink/90 px-3 py-2 text-xs text-paper/80 transition hover:text-paper focus-visible:ring-2 focus-visible:ring-brass focus-visible:outline-none"
      @click="mostrarCompetidores = !mostrarCompetidores"
    >
      {{ mostrarCompetidores ? 'Ocultar competidores' : 'Mostrar competidores' }}
    </button>

    <!-- Highlighted cluster -->
    <button
      v-if="seleccionados"
      type="button"
      class="absolute top-[4.75rem] left-3 z-10 flex items-center gap-2 rounded-lg border border-ambar/40 bg-ink/90 px-3 py-1.5 text-xs text-ambar transition hover:bg-ink focus-visible:ring-2 focus-visible:ring-ambar focus-visible:outline-none"
      @click="limpiarSeleccion"
    >
      <span>{{ seleccionados }} {{ seleccionados === 1 ? 'local resaltado' : 'locales resaltados' }}</span>
      <span class="text-paper/60">· Quitar</span>
    </button>

    <!-- Legend -->
    <ul
      v-if="codiDistricte && listo"
      class="pointer-events-none absolute bottom-8 left-3 z-10 space-y-1 rounded-lg border border-paper/10 bg-ink/90 px-3 py-2 text-[11px] text-paper/70"
      aria-label="Leyenda del mapa"
    >
      <li class="flex items-center gap-2">
        <span class="inline-block h-2.5 w-2.5 rounded-full bg-[#ff6f7d]" />Competidores
      </li>
      <li v-if="modo === 'radio'" class="flex items-center gap-2">
        <span class="inline-block h-2.5 w-2.5 rounded-full border-2 border-accent bg-white" />Ubicación elegida
      </li>
      <li v-if="seleccionados" class="flex items-center gap-2">
        <span class="inline-block h-2.5 w-2.5 rounded-full bg-ambar" />Grupo seleccionado
      </li>
    </ul>

    <!-- Status messages -->
    <p
      v-if="cargando"
      class="absolute top-16 left-1/2 z-10 -translate-x-1/2 rounded-full border border-paper/10 bg-ink/90 px-4 py-1.5 text-xs text-paper/70"
    >
      Cargando competidores…
    </p>
    <p
      v-if="error"
      class="absolute bottom-10 left-1/2 z-10 max-w-[85%] -translate-x-1/2 rounded-lg border border-rojo/40 bg-ink/95 px-4 py-2 text-center text-sm text-paper"
      role="alert"
    >
      {{ error }}
    </p>
    <p
      v-if="listo && !codiDistricte && !error"
      class="pointer-events-none absolute bottom-8 left-3 z-10 max-w-[70%] rounded-lg border border-paper/10 bg-ink/90 px-3 py-2 text-xs text-paper/60"
    >
      Escribe una dirección y el mapa te llevará allí, con los competidores y anillos de 100, 200 y 400 m.
    </p>
  </div>
</template>

<style>
/*
 * Dark skin for the MapLibre widgets (popup, zoom buttons, attribution).
 * Not scoped on purpose: MapLibre creates these elements outside this component.
 * Every rule starts with ".maplibregl-map" to be more specific than MapLibre's
 * own stylesheet, which is loaded later and would otherwise win.
 */
.maplibregl-map .maplibregl-popup-content {
  background: #121722;
  color: #e6eaf2;
  border: 1px solid rgb(230 234 242 / 0.15);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 12px;
  box-shadow: 0 6px 18px rgb(0 0 0 / 0.45);
}
.maplibregl-map .maplibregl-popup-anchor-bottom .maplibregl-popup-tip,
.maplibregl-map .maplibregl-popup-anchor-bottom-left .maplibregl-popup-tip,
.maplibregl-map .maplibregl-popup-anchor-bottom-right .maplibregl-popup-tip {
  border-top-color: #121722;
}
.maplibregl-map .maplibregl-popup-anchor-top .maplibregl-popup-tip,
.maplibregl-map .maplibregl-popup-anchor-top-left .maplibregl-popup-tip,
.maplibregl-map .maplibregl-popup-anchor-top-right .maplibregl-popup-tip {
  border-bottom-color: #121722;
}
.maplibregl-map .maplibregl-popup-anchor-left .maplibregl-popup-tip {
  border-right-color: #121722;
}
.maplibregl-map .maplibregl-popup-anchor-right .maplibregl-popup-tip {
  border-left-color: #121722;
}
.maplibregl-map .maplibregl-ctrl-group {
  background: #121722;
  border: 1px solid rgb(230 234 242 / 0.12);
  box-shadow: none;
}
.maplibregl-map .maplibregl-ctrl-group button + button {
  border-top: 1px solid rgb(230 234 242 / 0.12);
}
.maplibregl-map .maplibregl-ctrl-group button .maplibregl-ctrl-icon {
  filter: invert(1);
}
.maplibregl-map .maplibregl-ctrl-attrib {
  background: rgb(11 14 20 / 0.7);
  color: #9aa4b8;
}
.maplibregl-map .maplibregl-ctrl-attrib a {
  color: #9aa4b8;
}
</style>
