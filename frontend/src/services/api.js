/**
 * URL base de la API. Se obtiene de las variables de entorno de Vite.
 * @constant {string}
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

/**
 * Procesa la respuesta de Fetch, parseando el JSON o lanzando un error detallado.
 */
async function handleResponse(response) {
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const mensaje = body?.detail || `Error HTTP ${response.status}: Error al conectar con el servidor.`
    throw new Error(mensaje)
  }
  return response.json()
}

/**
 * Obtiene la lista de distritos disponibles.
 */
export async function obtenerDistritos() {
  const response = await fetch(`${API_BASE_URL}/api/distritos`)
  return handleResponse(response)
}

/**
 * Obtiene las zonas urbanísticas PGM.
 */
export async function obtenerZonasPgm() {
  const response = await fetch(`${API_BASE_URL}/api/zonas-pgm`)
  return handleResponse(response)
}

/**
 * Genera un informe de forma síncrona (completo de una vez).
 */
export async function generarInforme(codiDistricte, zonaPgm) {
  const response = await fetch(`${API_BASE_URL}/api/informes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ codi_districte: codiDistricte, zona_pgm: zonaPgm }),
  })
  return handleResponse(response)
}

/**
 * Obtiene el texto completo de un artículo legal.
 */
export async function obtenerArticulo(fuenteLegal, numeroArticulo) {
  const params = new URLSearchParams({ fuente_legal: fuenteLegal, numero_articulo: numeroArticulo })
  const response = await fetch(`${API_BASE_URL}/api/articulos?${params}`)
  return handleResponse(response)
}

/**
 * Obtiene la lista de competidores en un distrito.
 */
export async function obtenerCompetidores(codiDistricte) {
  const response = await fetch(`${API_BASE_URL}/api/competidores?codi_districte=${codiDistricte}`)
  return handleResponse(response)
}

/**
 * Consume el endpoint de informes mediante Server-Sent Events (streaming).
 *
 * Atrapa sus propios errores (red, HTTP, o un bloque SSE mal formado) y los
 * reporta vía el callback onError, en vez de dejarlos propagar hacia quien
 * llama -- así un solo fragmento corrupto del streaming no aborta todo lo
 * demás, solo se registra un aviso y continúa con el resto.
 */
export async function generarInformeStream(codiDistricte, zonaPgm, callbacks = {}) {
  const { onDatos, onToken, onDone, onError } = callbacks

  try {
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

      // Conservamos el último fragmento si está incompleto
      buffer = bloques.pop() ?? ''

      for (const bloque of bloques) {
        if (!bloque.startsWith('data: ')) continue

        try {
          const evento = JSON.parse(bloque.slice(6))
          if (evento.type === 'datos') onDatos?.(evento)
          else if (evento.type === 'token') onToken?.(evento.text)
          else if (evento.type === 'done') onDone?.(evento)
          else if (evento.type === 'error') onError?.(evento.detail)
        } catch (e) {
          console.warn('Error parseando bloque SSE:', bloque)
        }
      }
    }
  } catch (error) {
    onError?.(error.message)
  }
}