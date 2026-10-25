/**
 * ==============================================================================
 * MINIMAL MARKDOWN RENDERER (safe by construction)
 * ==============================================================================
 * File: frontend/src/utils/markdown.js
 *
 * The assistant answers in Markdown (headings, **bold**, lists, `code`, ---).
 * This turns that subset into HTML for `v-html`. The text is HTML-escaped FIRST
 * and only a fixed set of tags without attributes is added afterwards, so the
 * model output can never inject markup or scripts. Links and images are not
 * supported on purpose.
 *
 * It is also safe on half-received text: a `**` that is not closed yet stays as
 * plain text until the closing one arrives in the stream.
 */

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
const escapeHtml = (text) => text.replace(/[&<>"']/g, (c) => ESCAPES[c])

function inline(text) {
  return text
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^\w*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
}

export function renderMarkdown(source) {
  const out = []
  let list = null // 'ul' | 'ol' | null

  const closeList = () => {
    if (list) out.push(`</${list}>`)
    list = null
  }
  const openList = (tag) => {
    if (list === tag) return
    closeList()
    out.push(`<${tag}>`)
    list = tag
  }

  for (const rawLine of escapeHtml(String(source ?? '')).split('\n')) {
    const line = rawLine.trim()
    let match

    if (!line) {
      closeList()
    } else if (/^[-*_]{3,}$/.test(line)) {
      closeList()
      out.push('<hr>')
    } else if ((match = line.match(/^(#{1,6})\s+(.*)$/))) {
      closeList()
      const level = match[1].length <= 3 ? 3 : 4 // "#" to "###" are section titles, deeper ones are minor
      out.push(`<h${level}>${inline(match[2])}</h${level}>`)
    } else if ((match = line.match(/^[-*•]\s+(.*)$/))) {
      openList('ul')
      out.push(`<li>${inline(match[1])}</li>`)
    } else if ((match = line.match(/^\d+[.)]\s+(.*)$/))) {
      openList('ol')
      out.push(`<li>${inline(match[1])}</li>`)
    } else {
      closeList()
      out.push(`<p>${inline(line)}</p>`)
    }
  }
  closeList()
  return out.join('')
}
