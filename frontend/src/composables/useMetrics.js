/**
 * ==============================================================================
 * useMetrics: STATE AND DATA LOADING OF THE METRICS DASHBOARD
 * ==============================================================================
 * File: frontend/src/composables/useMetrics.js
 *
 * One time range scopes everything (KPIs, charts and the records table). The
 * records table adds its own filters, sorting and pagination.
 *
 * Behaviours worth knowing:
 *   - A slow answer that arrives after a newer request was sent is ignored, so
 *     the screen can never show a stale window.
 *   - While a reload runs, the previous data stays in place (`loading` is only a
 *     flag), so charts dim instead of flashing empty.
 *   - Changing a records filter goes back to page 1; typing in the trace id box
 *     waits for the typing to stop before asking the server.
 *   - Auto refresh pauses while the browser tab is hidden.
 */
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import { getMetricsOverview, getMetricsRequests } from '../services/api.js'
import { createLogger } from '../services/logger.js'

const log = createLogger('metrics')

export const RANGES = [
  { value: '24h', label: '24 horas' },
  { value: '7d', label: '7 días' },
  { value: '30d', label: '30 días' },
  { value: 'all', label: 'Todo' },
]
export const PAGE_SIZE = 25
const REFRESH_MS = 30_000
const DEBOUNCE_MS = 250

export function useMetrics() {
  const range = ref('24h')
  const overview = ref(null)
  const overviewLoading = ref(false)
  const overviewError = ref(null)

  const filters = reactive({
    status: '',
    route: '',
    model: '',
    trace_id: '',
    sort: 'created_at',
    direction: 'desc',
    offset: 0,
  })
  const page = ref(null)
  const pageLoading = ref(false)
  const pageError = ref(null)

  const autoRefresh = ref(false)
  const lastUpdated = ref(null)

  // Incremented on every request; only the newest one may write its answer.
  let overviewSeq = 0
  let pageSeq = 0

  async function loadOverview() {
    const seq = ++overviewSeq
    overviewLoading.value = true
    try {
      const data = await getMetricsOverview(range.value)
      if (seq !== overviewSeq) return
      overview.value = data
      overviewError.value = null
      lastUpdated.value = new Date()
    } catch (error) {
      if (seq !== overviewSeq) return
      overviewError.value = error.message
    } finally {
      if (seq === overviewSeq) overviewLoading.value = false
    }
  }

  async function loadPage() {
    const seq = ++pageSeq
    pageLoading.value = true
    try {
      const data = await getMetricsRequests({ range: range.value, limit: PAGE_SIZE, ...filters })
      if (seq !== pageSeq) return
      page.value = data
      pageError.value = null
    } catch (error) {
      if (seq !== pageSeq) return
      pageError.value = error.message
      log.warn('Could not load the request records', { error })
    } finally {
      if (seq === pageSeq) pageLoading.value = false
    }
  }

  const refresh = () => Promise.all([loadOverview(), loadPage()])

  // ---- Range: reloads everything and goes back to the first page.
  function setRange(value) {
    if (value === range.value) return
    range.value = value
    filters.offset = 0
    loadOverview()
  }

  // ---- Records: any change in the query reloads the table (debounced, so typing does not flood the API).
  function setFilter(key, value) {
    filters[key] = value
    filters.offset = 0
  }

  function setSort(column) {
    if (filters.sort === column) {
      filters.direction = filters.direction === 'desc' ? 'asc' : 'desc'
    } else {
      filters.sort = column
      filters.direction = 'desc'
    }
    filters.offset = 0
  }

  function goToOffset(offset) {
    filters.offset = Math.max(0, offset)
  }

  let debounce = null
  watch(
    () => JSON.stringify([range.value, { ...filters }]),
    () => {
      clearTimeout(debounce)
      debounce = setTimeout(loadPage, DEBOUNCE_MS)
    },
  )

  // ---- Auto refresh
  let timer = null
  watch(autoRefresh, (on) => {
    clearInterval(timer)
    timer = null
    if (on) {
      timer = setInterval(() => {
        if (!document.hidden) refresh()
      }, REFRESH_MS)
    }
  })

  onMounted(refresh)
  onBeforeUnmount(() => {
    clearTimeout(debounce)
    clearInterval(timer)
  })

  return {
    range,
    overview,
    overviewLoading,
    overviewError,
    filters,
    page,
    pageLoading,
    pageError,
    autoRefresh,
    lastUpdated,
    refresh,
    setRange,
    setFilter,
    setSort,
    goToOffset,
  }
}
