/**
 * ==============================================================================
 * CHART THEME (colors and shared ECharts options)
 * ==============================================================================
 * File: frontend/src/utils/chartTheme.js
 *
 * Colors were validated against the dashboard card surface (about #1c2b44,
 * the "ink-light" panel over "ink") with the dataviz palette validator:
 * lightness band, chroma, color-blind separation of neighbors, and contrast.
 *
 * Rules the charts follow:
 *   - A color belongs to an ENTITY (an actor, a token direction), never to a
 *     rank, so a filter never repaints the survivors.
 *   - Series colors are assigned in this fixed order. Never add a ninth.
 *   - ok / error / cancelled use the fixed status colors, and always appear
 *     next to a text label.
 *   - Text uses ink tokens, never the series color.
 */

/** Categorical slots, dark-surface steps, in fixed order. */
export const SERIES = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181']

/** Fixed status colors. Warning/critical are < 3:1 by design, hence the text label next to every use. */
export const STATUS = { ok: '#0ca30c', error: '#d03b3b', cancelled: '#898781' }
export const STATUS_LABEL = { ok: 'Correcta', error: 'Con error', cancelled: 'Cancelada' }

/** One color per pipeline actor. Same order as the backend `Actor` type. */
const ACTORS = {
  agent: { label: 'Agente', color: SERIES[0] },
  llm: { label: 'LLM', color: SERIES[1] },
  rag: { label: 'RAG', color: SERIES[2] },
  db: { label: 'Base de datos', color: SERIES[3] },
  external: { label: 'Externo', color: SERIES[4] },
}
const OTHER_ACTOR = { label: 'Otros', color: '#898781' }
export const actorInfo = (actor) => ACTORS[actor] ?? { ...OTHER_ACTOR, label: actor || OTHER_ACTOR.label }

/** Entities that are not actors. */
export const COLORS = {
  requests: SERIES[0],
  latencyAvg: SERIES[0],
  latencyP95: SERIES[1],
  tokensIn: SERIES[0],
  tokensOut: SERIES[1],
  cost: SERIES[2],
  cache: SERIES[2],
}

export const INK = {
  primary: '#f5f1e8',
  secondary: '#c3c2b7',
  muted: '#a3a199',
  grid: 'rgba(245, 241, 232, 0.08)',
  axis: 'rgba(245, 241, 232, 0.2)',
  surface: '#1c2b44',
}

const FONT = "'IBM Plex Sans', system-ui, sans-serif"

/** Escapes text that comes from the API (route and model names) before it goes into tooltip HTML. */
function esc(value) {
  return String(value ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  )
}

/**
 * Tooltip body: title, then one row per series with a short color key, the value
 * first and the name second.
 *
 * @param {string} title
 * @param {Array<{ color?: string, name: string, value: string }>} rows
 */
export function tooltipHtml(title, rows) {
  const lines = rows
    .map(
      (r) =>
        `<div style="display:flex;align-items:center;gap:8px;margin-top:3px">` +
        (r.color ? `<span style="width:10px;height:2px;border-radius:1px;background:${r.color}"></span>` : '') +
        `<strong style="color:${INK.primary};font-weight:600;font-variant-numeric:tabular-nums">${esc(r.value)}</strong>` +
        `<span style="color:${INK.secondary}">${esc(r.name)}</span></div>`,
    )
    .join('')
  return `<div style="font-size:12px"><div style="color:${INK.secondary};margin-bottom:2px">${esc(title)}</div>${lines}</div>`
}

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** Options every chart shares: quiet hairline grid, text tokens, tooltip that follows the axis. */
export function baseOption({ legend = false } = {}) {
  return {
    animation: !prefersReducedMotion(),
    animationDuration: 400,
    textStyle: { fontFamily: FONT, color: INK.secondary },
    grid: { left: 8, right: 16, top: legend ? 36 : 12, bottom: 4, containLabel: true },
    legend: legend
      ? {
          top: 0,
          left: 0,
          itemWidth: 14,
          itemHeight: 3,
          icon: 'roundRect',
          textStyle: { color: INK.secondary, fontSize: 12 },
          inactiveColor: INK.axis,
        }
      : undefined,
    tooltip: {
      confine: true,
      backgroundColor: '#0e1829',
      borderColor: 'rgba(245, 241, 232, 0.15)',
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: INK.primary, fontFamily: FONT },
      extraCssText: 'box-shadow:0 8px 24px rgba(0,0,0,.4);',
    },
  }
}

/** Category axis (bars, time buckets). */
export function categoryAxis(data, extra = {}) {
  return {
    type: 'category',
    data,
    axisLine: { lineStyle: { color: INK.axis } },
    axisTick: { show: false },
    axisLabel: { color: INK.muted, fontSize: 11, hideOverlap: true },
    ...extra,
  }
}

/** Value axis with hairline solid grid lines. */
export function valueAxis(formatter, extra = {}) {
  return {
    type: 'value',
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: INK.grid, type: 'solid' } },
    axisLabel: { color: INK.muted, fontSize: 11, formatter },
    ...extra,
  }
}

/** Round the data end of a bar (4 px) and keep the baseline end square. */
export const BAR_RADIUS_UP = [4, 4, 0, 0]
export const BAR_RADIUS_RIGHT = [0, 4, 4, 0]
/** Bars never fill their slot: thin marks, and the leftover is air. */
export const BAR_MAX_WIDTH = 24
