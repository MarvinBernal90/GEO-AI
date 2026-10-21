<!--
==============================================================================
CHAT PANEL (UNIFIED CHAT)
==============================================================================
File: frontend/src/components/ChatPanel.vue

Presentational component: shows the conversation bubbles, the message box,
the compact login and the conversation selector. It owns no business state:
everything comes in by props and goes out by events.
-->
<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  sending: { type: Boolean, default: false },
  username: { type: String, default: null },
  loggingIn: { type: Boolean, default: false },
  loginError: { type: String, default: '' },
  conversations: { type: Array, default: () => [] },
  articles: { type: Array, default: () => [] },
})

const emit = defineEmits(['login', 'send', 'cancel', 'clear', 'select-conversation', 'ver-articulo'])

const usuario = defineModel('usuario', { type: String, default: '' })
const conversacion = defineModel('conversacion', { type: String, default: '' })

const draft = ref('')
const listEl = ref(null)
let followBottom = true // stops following when the user scrolls up

// Empty assistant bubbles (waiting for the first token) are shown as "typing".
const visibleMessages = computed(() => props.messages.filter((message) => message.text))
const showTyping = computed(() => {
  if (!props.sending) return false
  const last = props.messages.at(-1)
  return !last || last.role === 'user' || (last.kind === 'texto' && !last.text)
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

watch(() => props.messages.map((message) => message.text.length).join(','), scrollToBottom)
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
  <section class="space-y-4 rounded-xl border border-paper/15 bg-ink-light/50 p-5 shadow-lg backdrop-blur-sm">
    <!-- Header: title, state and user -->
    <header class="space-y-3 border-b border-paper/10 pb-4">
      <div class="flex items-center justify-between gap-3">
        <h2 class="font-display text-xl font-semibold text-paper">Asistente de viabilidad</h2>
        <span v-if="sending" class="flex items-center gap-1.5 font-mono text-xs text-brass">
          <span class="h-2 w-2 animate-ping rounded-full bg-brass motion-reduce:animate-none" />
          Trabajando…
        </span>
        <span v-else class="font-mono text-xs text-paper/40">En espera</span>
      </div>
      <p class="text-xs leading-relaxed text-paper/60">
        Escribe una dirección de Barcelona para generar un informe, o pregunta por licencias y normativa.
      </p>

      <!-- Login -->
      <div v-if="!username" class="space-y-1.5">
        <div class="flex items-center gap-2">
          <label for="chat-user" class="sr-only">Usuario</label>
          <input
            id="chat-user"
            v-model="usuario"
            type="text"
            placeholder="Usuario (para guardar conversaciones)"
            class="flex-1 rounded border border-paper/20 bg-ink px-3 py-1.5 text-xs text-paper placeholder:text-paper/30 focus:border-brass focus:ring-1 focus:ring-brass focus:outline-none"
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
        <p v-else class="text-[11px] text-paper/40">
          Sin usuario solo puedes generar informes. Con usuario también responde el asistente y se guarda el historial.
        </p>
      </div>

      <!-- Active user and conversation selector -->
      <div v-else class="space-y-2">
        <p class="flex items-center gap-1.5 text-xs text-paper/70">
          <span class="h-1.5 w-1.5 rounded-full bg-verde" aria-hidden="true" />
          Sesión de <strong class="font-medium text-paper">{{ username }}</strong>
        </p>
        <label for="chat-conversation" class="sr-only">Conversación</label>
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
      </div>
    </header>

    <!-- Conversation -->
    <div
      ref="listEl"
      class="max-h-[28rem] min-h-[14rem] space-y-3 overflow-y-auto pr-1"
      role="log"
      aria-live="polite"
      aria-label="Conversación"
      @scroll="onScroll"
    >
      <p v-if="visibleMessages.length === 0 && !showTyping" class="py-10 text-center text-sm text-paper/40">
        Todavía no hay mensajes. Prueba con: «Quiero abrir un bar en Carrer de Sant Pau 1».
      </p>

      <div
        v-for="message in visibleMessages"
        :key="message.id"
        class="max-w-[90%] rounded-2xl border px-4 py-2.5 text-sm leading-relaxed whitespace-pre-line"
        :class="bubbleClass(message)"
      >
        {{ message.text }}
      </div>

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

    <!-- Cited articles of the last report -->
    <div v-if="articles.length > 0" class="border-t border-paper/10 pt-3">
      <p class="mb-1.5 text-xs text-paper/60">Artículos citados en el informe</p>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="articulo in articles"
          :key="`${articulo.fuente_legal}-${articulo.numero_articulo}`"
          type="button"
          class="rounded-full border border-brass/30 bg-brass/10 px-3 py-1 font-mono text-xs text-brass transition hover:bg-brass hover:text-ink focus-visible:ring-2 focus-visible:ring-brass focus-visible:outline-none"
          title="Abrir visor de normativa"
          @click="emit('ver-articulo', articulo)"
        >
          Art. {{ articulo.numero_articulo }}
        </button>
      </div>
    </div>

    <!-- Message box -->
    <form class="space-y-2 border-t border-paper/10 pt-4" @submit.prevent="submit">
      <label for="chat-input" class="sr-only">Mensaje</label>
      <textarea
        id="chat-input"
        v-model="draft"
        rows="3"
        placeholder="Escribe tu consulta…"
        class="w-full resize-y rounded-lg border border-paper/20 bg-ink px-3.5 py-2.5 text-sm text-paper placeholder:text-paper/30 focus:border-brass focus:ring-1 focus:ring-brass focus:outline-none"
        @keydown.enter.exact.prevent="submit"
      />
      <div class="flex items-center justify-between gap-3">
        <div class="flex items-center gap-3 text-[11px] text-paper/40">
          <span>Enter envía · Mayús+Enter salto de línea</span>
          <button
            v-if="messages.length > 0 && !sending"
            type="button"
            class="text-paper/50 transition hover:text-paper"
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
  </section>
</template>
