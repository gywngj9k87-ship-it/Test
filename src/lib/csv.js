/*
 * Minimal CSV / delimited-text parsing for the live data sources.
 * These feeds (NOAA, Our World in Data) are plain, well-formed CSV without
 * embedded newlines, so a light parser is enough and keeps the bundle small.
 */

// Parse simple CSV text into an array of row objects keyed by header.
// `commentPrefix` skips leading metadata/comment lines (NOAA uses '#').
export function parseCsv(text, { commentPrefix = null } = {}) {
  const lines = text
    .split(/\r?\n/)
    .filter((l) => l.trim() !== '' && (!commentPrefix || !l.startsWith(commentPrefix)))
  if (lines.length < 2) return []
  const headers = splitLine(lines[0]).map((h) => h.trim())
  const rows = []
  for (let i = 1; i < lines.length; i++) {
    const cells = splitLine(lines[i])
    const row = {}
    headers.forEach((h, idx) => {
      row[h] = cells[idx] !== undefined ? cells[idx].trim() : ''
    })
    rows.push(row)
  }
  return rows
}

function splitLine(line) {
  // Handles basic quoted fields; sufficient for the feeds we consume.
  const out = []
  let cur = ''
  let inQuotes = false
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]
    if (ch === '"') {
      inQuotes = !inQuotes
    } else if (ch === ',' && !inQuotes) {
      out.push(cur)
      cur = ''
    } else {
      cur += ch
    }
  }
  out.push(cur)
  return out
}

export function toNumber(v) {
  const n = parseFloat(v)
  return Number.isFinite(n) ? n : null
}
