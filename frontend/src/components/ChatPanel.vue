<!--
==============================================================================
CHAT PANEL (UNIFIED CHAT, FULL HEIGHT)
==============================================================================
File: frontend/src/components/ChatPanel.vue

Presentational component: the conversation, the message box, the compact
account button and the conversation selector. The guided search form comes in
through the "guided" slot and opens as a floating panel above the message box.
It owns no business state: everything comes in by props and goes out by events.
-->
<script setup>
import { computed, nextTick, ref, watch } from 'vue'

import ReportMessage from './ReportMessage.vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  sending: { type: Boolean, default: false },
  username: { type: String, default: null },
  loggingIn: { type: Boolean, default: false },
  loginError: { type: String, default: '' },
  conversations: { type: Array, default: () => [] },
})

const emit = defineEmits(['login', 'send', 'cancel', 'clear', 'select-conversation', 'ver-articulo'])

const usuario = defineModel('usuario', { type: String, default: '' })
const conversacion = defineModel('conversacion', { type: String, default: '' })
const guidedOpen = defineModel('guidedOpen', { type: Boolean, default: false })

const draft = ref('')
const listEl = ref(null)
const cuentaAbierta = ref(false) // account popover (login or conversation selector)
let followBottom = true // stops following when the user scrolls up

// Close the account popover as soon as the login works.
watch(
  () => props.username,
  (nuevo) => {
    if (nuevo) cuentaAbierta.value = false
  },
)

// Empty assistant bubbles (waiting for the first token) are hidden: the
// "typing" dots are shown instead. Reports are always shown.
const visibleMessages = computed(() => props.messages.filter((m) => m.kind === 'informe' || m.text))
const showTyping = computed(() => {
  if (!props.sending) return false
  const last = props.messages.at(-1)
  return !last || last.role === 'user' || (last.kind === 'texto' && !last.text)
})

// Changes whenever the conversation grows, so the list can follow the bottom.
const scrollKey = computed(() => {
  const last = props.messages.at(-1)
  if (!last) return ''
  if (last.kind === 'informe') {
    const r = last.report
    return `${props.messages.length}:${r.status}:${r.texto.length}:${r.respuestaLegal.length}`
  }
  return `${props.messages.length}:${last.text.length}`
})

function onScroll() {
  const el = listEl.value
  if (!el) return
  followBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

function scrollToBottom() {
  nextTick(() => {
    if (followBottom && listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
  })
}

watch(scrollKey, scrollToBottom)
watch(showTyping, scrollToBottom)

function submit() {
  const text = draft.value.trim()
  if (!text || props.sending) return
  followBottom = true
  emit('send', text)
  draft.value = ''
}

function onSelectChange(event) {
  conversacion.value = event.target.value
  emit('select-conversation')
  cuentaAbierta.value = false
}

const BUBBLE_CLASSES = {
  user: 'ml-auto rounded-br-sm border-brass/30 bg-brass/15 text-paper',
  texto: 'mr-auto rounded-tl-sm border-paper/10 bg-ink-light text-paper/90',
  aviso: 'mr-auto rounded-tl-sm border-brass/40 bg-brass/10 text-paper/90',
  error: 'mr-auto rounded-tl-sm border-rojo/40 bg-rojo/10 text-paper',
}

function bubbleClass(message) {
  return BUBBLE_CLASSES[message.role === 'user' ? 'user' : message.kind] ?? BUBBLE_CLASSES.texto
}
</script>

<template>
  <section class="relative flex h-full min-h-0 flex-col border-paper/10 bg-ink lg:border-r">
    <!-- Header: title and account button (one line) -->
    <header class="relative flex items-center justify-between gap-3 border-b border-paper/10 px-5 py-3">
      <div class="min-w-0">
        <p class="font-mono text-[10px] font-bold tracking-[0.2em] text-brass uppercase">Geo-Yield-AI</p>
        <h1 class="truncate font-display text-lg font-semibold text-paper">Asistente de viabilidad</h1>
      </div>

      <button
        v-if="!username"
        type="button"
        class="shrink-0 rounded-md border border-paper/15 px-3 py-1.5 text-xs text-paper/80 transition hover:text-paper focus-visible:ring-2 focus-visible:ring-brass focus-visible:outline-none"
        :aria-expanded="cuentaAbierta"
        @click="cuentaAbierta = !cuentaAbierta"
      >
        Iniciar sesión
      </button>
      <button
        v-else
        type="button"
        class="flex shrink-0 items-center gap-2 rounded-md border border-paper/15 px-3 py-1.5 text-xs text-paper/80 transition hover:text-paper focus-visible:ring-2 focus-visible:ring-brass focus-visible:outline-none"
        :aria-expanded="cuentaAbierta"
        aria-label="Cuenta y conversaciones"
        @click="cuentaAbierta = !cuentaAbierta"
      >
        <span class="h-1.5 w-1.5 rounded-full bg-verde" aria-hidden="true" />
        <span class="max-w-[8rem] truncate font-medium text-paper">{{ username }}</span>
        <span aria-hidden="true">▾</span>
      </button>

      <!-- Account popover: login, or conversation selector once logged in -->
      <div
        v-if="cuentaAbierta"
        class="absolute top-full right-4 z-30 mt-1 w-72 space-y-2 rounded-xl border border-paper/15 bg-ink-light p-3 shadow-2xl"
        @keydown.esc="cuentaAbierta = false"
      >
        <template v-if="!username">
          <div class="flex items-center gap-2">
            <label for="chat-user" class="sr-only">Usuario</label>
            <input
              id="chat-user"
              v-model="usuario"
              type="text"
              placeholder="Tu usuario"
              class="min-w-0 flex-1 rounded border border-paper/20 bg-ink px-3 py-1.5 text-xs text-paper placeholder:text-paper/30 focus:border-brass focus:ring-1 focus:ring-brass focus:outline-none"
              @keydown.enter.prevent="emit('login')"
            />
            <button
              type="button"
              :disabled="!usuario.trim() || loggingIn"
              class="shrink-0 rounded bg-brass px-3 py-1.5 text-xs font-medium text-ink transition hover:bg-brass/90 disabled:cursor-not-allowed disabled:opacity-40"
              @click="emit('login')"
            >
              {{ loggingIn ? 'Verificando…' : 'Entrar' }}
            </button>
          </div>
          <p v-if="loginError" class="text-xs text-rojo" role="alert">{{ loginError }}</p>
          <p v-else class="text-[11px] leading-snug text-paper/50">
            Sin usuario solo se generan informes. Con usuario, además, el asistente responde y se guarda el historial.
          </p>
        </template>

        <template v-else>
          <label for="chat-conversation" class="block text-[11px] text-paper/60">Conversación</label>
          <select
            id="chat-conversation"
            :value="conversacion"
            :disabled="sending"
            class="w-full rounded border border-paper/20 bg-ink px-3 py-1.5 text-xs text-paper focus:border-brass focus:ring-1 focus:ring-brass focus:outline-none disabled:opacity-50"
            @change="onSelectChange"
          >
            <option value="">Nueva conversación</option>
            <option v-for="c in conversations" :key="c.id" :value="c.id">{{ c.title }}</option>
          </select>
        </template>
      </div>
    </header>

    <!-- Conversation -->
    <div
      ref="listEl"
      class="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4"
      role="log"
      aria-live="polite"
      aria-label="Conversación"
      @scroll="onScroll"
    >
      <p
        v-if="visibleMessages.length === 0 && !showTyping"
        class="py-10 text-center text-sm leading-relaxed text-paper/40"
      >
        Escribe una dirección de Barcelona para generar un informe, o pregunta por licencias y normativa.<br />
        Por ejemplo: «Quiero abrir un bar en Carrer de Sant Pau 1».
      </p>

      <template v-for="message in visibleMessages" :key="message.id">
        <ReportMessage
          v-if="message.kind === 'informe'"
          :report="message.report"
          @ver-articulo="emit('ver-articulo', $event)"
        />
        <div
          v-else
          class="max-w-[90%] rounded-2xl border px-4 py-2.5 text-sm leading-relaxed whitespace-pre-line"
          :class="bubbleClass(message)"
        >
          {{ message.text }}
        </div>
      </template>

      <div
        v-if="showTyping"
        class="mr-auto flex w-fit items-center gap-1.5 rounded-2xl rounded-tl-sm border border-paper/10 bg-ink-light px-4 py-3"
        aria-label="Escribiendo"
      >
        <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-paper/50 motion-reduce:animate-none" />
        <span
          class="h-1.5 w-1.5 animate-pulse rounded-full bg-paper/50 [animation-delay:150ms] motion-reduce:animate-none"
        />
        <span
          class="h-1.5 w-1.5 animate-pulse rounded-full bg-paper/50 [animation-delay:300ms] motion-reduce:animate-none"
        />
      </div>
    </div>

    <!-- Message box (with the guided search panel floating above it) -->
    <div class="relative border-t border-paper/10">
      <!-- v-show keeps the form mounted, so it can still be pre-filled while closed -->
      <div
        v-show="guidedOpen"
        class="absolute inset-x-3 bottom-full z-20 mb-2 max-h-[65vh] overflow-y-auto rounded-xl border border-paper/15 bg-ink-light p-4 shadow-2xl"
        role="dialog"
        aria-label="Búsqueda guiada"
      >
        <div class="mb-3 flex items-start justify-between gap-3">
          <div>
            <p class="font-mono text-[10px] font-semibold tracking-widest text-brass uppercase">Búsqueda guiada</p>
            <p class="mt-0.5 text-xs text-paper/60">Elige tú el distrito y la zona.</p>
          </div>
          <button
            type="button"
            class="rounded-full px-2 py-0.5 text-sm text-paper/50 transition hover:bg-paper/10 hover:text-paper focus-visible:ring-2 focus-visible:ring-brass focus-visible:outline-none"
            aria-label="Cerrar búsqueda guiada"
            @click="guidedOpen = false"
          >
            ✕
          </button>
        </div>
        <slot name="guided" />
      </div>

      <form class="space-y-2 px-5 py-3" @submit.prevent="submit">
        <label for="chat-input" class="sr-only">Mensaje</label>
        <textarea
          id="chat-input"
          v-model="draft"
          rows="2"
          placeholder="Escribe tu consulta…"
          title="Enter envía · Mayús+Enter salto de línea"
          class="w-full resize-none rounded-lg border border-paper/20 bg-ink-light px-3.5 py-2.5 text-sm text-paper placeholder:text-paper/30 focus:border-brass focus:ring-1 focus:ring-brass focus:outline-none"
          @keydown.enter.exact.prevent="submit"
        />
        <div class="flex items-center justify-between gap-3">
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="rounded-md border px-2.5 py-1.5 text-xs transition focus-visible:ring-2 focus-visible:ring-brass focus-visible:outline-none"
              :class="
                guidedOpen ? 'border-brass/50 bg-brass/10 text-brass' : 'border-paper/15 text-paper/70 hover:text-paper'
              "
              :aria-expanded="guidedOpen"
              @click="guidedOpen = !guidedOpen"
            >
              Búsqueda guiada
            </button>
            <button
              v-if="messages.length > 0 && !sending"
              type="button"
              class="px-2 py-1.5 text-xs text-paper/50 transition hover:text-paper"
              @click="emit('clear')"
            >
              Vaciar chat
            </button>
          </div>
          <button
            v-if="sending"
            type="button"
            class="rounded border border-paper/30 px-4 py-2 text-sm text-paper transition hover:bg-paper/10 focus-visible:ring-2 focus-visible:ring-brass focus-visible:outline-none"
            @click="emit('cancel')"
          >
            Detener
          </button>
          <button
            v-else
            type="submit"
            :disabled="!draft.trim()"
            class="rounded bg-brass px-4 py-2 text-sm font-medium text-ink transition hover:bg-brass/90 focus-visible:ring-2 focus-visible:ring-paper focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40"
          >
            Enviar
          </button>
        </div>
      </form>
    </div>
  </section>
</template>
