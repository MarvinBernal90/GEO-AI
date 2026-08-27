<script setup>
defineProps({
  informe: { type: Object, required: true },
})
</script>

<template>
  <div class="flex gap-3">
    <div
      class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-brass/40 bg-ink-light font-display text-sm text-brass"
      aria-hidden="true"
    >
      GY
    </div>
    <div class="flex-1 space-y-3 rounded-lg rounded-tl-none border border-paper/10 bg-ink-light px-5 py-4">
      <div>
        <p class="mb-1 text-[11px] tracking-widest text-paper/40 uppercase">Fundamento legal</p>
        <p class="text-sm leading-relaxed whitespace-pre-line text-paper/90">{{ informe.respuesta_legal }}</p>
      </div>

      <div v-if="informe.articulos_citados?.length" class="flex flex-wrap gap-1.5 border-t border-paper/10 pt-3">
        <span
          v-for="articulo in informe.articulos_citados"
          :key="articulo"
          class="rounded border border-brass/30 bg-brass/10 px-2 py-0.5 font-mono text-xs text-brass"
        >
          Art. {{ articulo }}
        </span>
      </div>
    </div>
  </div>
</template>
