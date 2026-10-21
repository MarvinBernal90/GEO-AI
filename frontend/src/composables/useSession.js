/**
 * ==============================================================================
 * SESSION STATE (LOGIN + CONVERSATIONS)
 * ==============================================================================
 * File: frontend/src/composables/useSession.js
 *
 * Keeps the user name, the list of saved conversations and the thread id of
 * the active conversation. The thread id has the form "<user>:<number>" and is
 * what the backend uses to keep the memory and the history of a conversation.
 *
 * Without a user there is no thread id (empty string): the chat then only
 * generates reports and does not keep any history.
 */

import { computed, ref, watch } from 'vue'

import { loginUser } from '../services/api.js'
import { createLogger } from '../services/logger.js'

const log = createLogger('app.sesion')

const NEW_CONVERSATION = 'nueva conversación'
const STORAGE_CONVERSATION = 'geoyield_conversation'
const STORAGE_USER = 'geoyield_user'

/** Reads localStorage without crashing in private mode or when it is blocked. */
function readStorage(key) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

/** Writes (or removes, when value is null) a localStorage key. Never throws. */
function writeStorage(key, value) {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    // Storage is only a convenience: the app works without it.
  }
}

export function useSession() {
  const usuario = ref('') // what the user is typing in the login box
  const username = ref(null) // the verified user, or null
  const loginError = ref('')
  const cargandoLogin = ref(false)
  const conversaciones = ref([]) // [{ id, title }]
  const conversacionSeleccionada = ref(readStorage(STORAGE_CONVERSATION) || '')

  const esNueva = computed(() => !conversacionSeleccionada.value || conversacionSeleccionada.value === NEW_CONVERSATION)

  const threadId = computed(() => {
    if (!username.value) return ''
    if (esNueva.value) return `${username.value}:${conversaciones.value.length + 1}`
    const selected = conversacionSeleccionada.value
    return selected.includes(':') ? selected : `${username.value}:${selected}`
  })

  // Some logging code reads these globals to add the user to every log line.
  watch(
    [username, threadId],
    ([user, thread]) => {
      if (typeof window === 'undefined') return
      window.username = user
      window.thread_id = thread
    },
    { immediate: true },
  )

  /** Verifies the user in the backend and loads the saved conversations. */
  async function login() {
    const nombre = usuario.value.trim()
    loginError.value = ''

    if (!nombre) {
      username.value = null
      conversaciones.value = []
      conversacionSeleccionada.value = ''
      return
    }
    if (cargandoLogin.value) return

    cargandoLogin.value = true
    try {
      const data = await loginUser(nombre)
      username.value = data.user
      writeStorage(STORAGE_USER, data.user)
      conversaciones.value = data.conversations || []
      conversacionSeleccionada.value = ''
      log.event('user.login.success', { user: data.user, conversations_count: conversaciones.value.length })
    } catch (err) {
      loginError.value = err.message || 'No se pudo iniciar sesión.'
      username.value = null
      writeStorage(STORAGE_USER, null)
      conversaciones.value = []
      conversacionSeleccionada.value = ''
      log.event('user.login.error', { user: nombre, error: err.message })
    } finally {
      cargandoLogin.value = false
    }
  }

  /**
   * Registers the conversation of the first message as a new entry of the list
   * and selects it. Does nothing without a user or in an existing conversation.
   * PRIVACY: the title is the user's first message, so it is never logged.
   */
  function ensureConversation(title) {
    if (!username.value || !esNueva.value) return
    const id = threadId.value
    conversaciones.value = [...conversaciones.value, { id, title }]
    conversacionSeleccionada.value = id
    writeStorage(STORAGE_CONVERSATION, id)
    log.event('conversation.created', { conversation_id: id, user: username.value })
  }

  /** Remembers the selected conversation (call it after the selection changes). */
  function persistSelection() {
    writeStorage(STORAGE_CONVERSATION, esNueva.value ? null : conversacionSeleccionada.value)
    log.event('conversation.selected', {
      conversation_id: esNueva.value ? 'nueva_conversacion' : conversacionSeleccionada.value,
      user: username.value,
    })
  }

  return {
    usuario,
    username,
    loginError,
    cargandoLogin,
    conversaciones,
    conversacionSeleccionada,
    esNueva,
    threadId,
    login,
    ensureConversation,
    persistSelection,
  }
}
