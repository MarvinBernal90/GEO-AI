/**
 * ==============================================================================
 * useRagEvals: STATE AND DATA LOADING OF THE RAG QUALITY DASHBOARD
 * ==============================================================================
 * File: frontend/src/composables/useRagEvals.js
 *
 * Loads the list of evaluation runs once, keeps one question set selected ("dev" or "holdout"),
 * and loads the full detail (every question) of the selected run on demand.
 *
 * Behaviours worth knowing:
 *   - Runs are only comparable inside one question set, so the table and charts show a single set.
 *   - The newest run of the set that measured answers is selected by default (else the newest); choosing another one loads its detail.
 *   - A slow answer for a run that is no longer selected is ignored.
 *   - The corpus report is optional: a missing one does not break the screen.
 */
import { computed, onMounted, ref, watch } from 'vue'

import { getEvalCorpus, getEvalRun, getEvalRuns } from '../services/api.js'
import { createLogger } from '../services/logger.js'

const log = createLogger('evals')

export const SETS = [
  { value: 'dev', label: 'Desarrollo', hint: 'Con este conjunto se ajusta el sistema.' },
  { value: 'holdout', label: 'Reserva', hint: 'No se toca al ajustar: confirma que la mejora es real.' },
]

export function useRagEvals() {
  const runs = ref([])
  const loading = ref(false)
  const error = ref(null)
  const selectedSet = ref('dev')
  const selectedId = ref(null)
  const detail = ref(null)
  const detailLoading = ref(false)
  const detailError = ref(null)
  const corpus = ref(null)

  let detailSeq = 0

  const setRuns = computed(() => runs.value.filter((r) => r.set === selectedSet.value))
  const setCounts = computed(() => {
    const counts = {}
    for (const r of runs.value) counts[r.set] = (counts[r.set] ?? 0) + 1
    return counts
  })
  const selected = computed(() => runs.value.find((r) => r.run_id === selectedId.value) ?? null)

  async function loadRuns() {
    loading.value = true
    try {
      runs.value = (await getEvalRuns()).runs
      error.value = null
      // Land on the set that has runs, so the first screen is never empty when the other one is not.
      if (!setRuns.value.length && runs.value.length) selectedSet.value = runs.value[0].set
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
    try {
      corpus.value = await getEvalCorpus()
    } catch (e) {
      log.warn('corpus report not available', { error: e })
      corpus.value = null
    }
  }

  async function loadDetail(id) {
    const seq = ++detailSeq
    detail.value = null
    detailError.value = null
    if (!id) return
    detailLoading.value = true
    try {
      const data = await getEvalRun(id)
      if (seq === detailSeq) detail.value = data
    } catch (e) {
      if (seq === detailSeq) detailError.value = e.message
    } finally {
      if (seq === detailSeq) detailLoading.value = false
    }
  }

  function select(id) {
    selectedId.value = id
  }

  // Changing the set, or new runs arriving, falls back to the newest run of the set.
  watch(
    [selectedSet, runs],
    () => {
      if (setRuns.value.some((r) => r.run_id === selectedId.value)) return
      // Prefer the newest run that also measured answers: it fills every tile of the screen.
      const preferred = setRuns.value.find((r) => r.answers) ?? setRuns.value[0]
      selectedId.value = preferred?.run_id ?? null
    },
    { immediate: true },
  )
  watch(selectedId, loadDetail)

  onMounted(loadRuns)

  return {
    runs,
    loading,
    error,
    selectedSet,
    selectedId,
    selected,
    setRuns,
    setCounts,
    detail,
    detailLoading,
    detailError,
    corpus,
    select,
    reload: loadRuns,
  }
}
