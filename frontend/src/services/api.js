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

export async function obtenerCompetidores(codiDistricte) {
  const response = await fetch(`${API_BASE_URL}/api/competidores?codi_districte=${codiDistricte}`)
  return handleResponse(response)
}

// Consume el endpoint de streaming (Server-Sent Events). No se usa
// EventSource porque solo soporta peticiones GET, y aquí hace falta
// enviar distrito+zona en el cuerpo de una petición POST -- se lee el
// cuerpo de la respuesta como un stream de bytes en su lugar.
export async function generarInformeStream(codiDistricte, zonaPgm, { onDatos, onToken, onDone, onError } = {}) {
  const response = await fetch(`${API_BASE_URL}/api/informes/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ codi_districte: codiDistricte, zona_pgm: zonaPgm }),
  })

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail || `Error ${response.status} al llamar a la API`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const bloques = buffer.split('\n\n')
    buffer = bloques.pop() ?? '' // el último bloque puede estar incompleto, se conserva para la siguiente vuelta

    for (const bloque of bloques) {
      if (!bloque.startsWith('data: ')) continue
      const evento = JSON.parse(bloque.slice(6))
      if (evento.type === 'datos') onDatos?.(evento)
      else if (evento.type === 'token') onToken?.(evento.text)
      else if (evento.type === 'done') onDone?.(evento)
      else if (evento.type === 'error') onError?.(evento.detail)
    }
  }
}