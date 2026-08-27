// Centraliza las llamadas al backend. La URL base se lee de una variable
// de entorno de Vite (VITE_API_BASE_URL), con localhost:8000 como valor
// por defecto para desarrollo -- así no hay que tocar código para apuntar
// a un backend desplegado más adelante, solo el fichero .env del frontend.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function handleResponse(response) {
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const mensaje = body?.detail || `Error ${response.status} al llamar a la API`
    throw new Error(mensaje)
  }
  return response.json()
}

export async function obtenerDistritos() {
  const response = await fetch(`${API_BASE_URL}/api/distritos`)
  return handleResponse(response)
}

export async function obtenerZonasPgm() {
  const response = await fetch(`${API_BASE_URL}/api/zonas-pgm`)
  return handleResponse(response)
}

export async function generarInforme(codiDistricte, zonaPgm) {
  const response = await fetch(`${API_BASE_URL}/api/informes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ codi_districte: codiDistricte, zona_pgm: zonaPgm }),
  })
  return handleResponse(response)
}
