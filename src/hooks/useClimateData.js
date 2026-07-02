import { useCallback, useEffect, useRef, useState } from 'react'
import { SNAPSHOTS, SNAPSHOT_AS_OF } from '../data/snapshots.js'
import { refreshDataset, hasLiveSource } from '../lib/fetchers.js'

/*
 * Central data store for the dashboard.
 *
 * - Seeds every dataset from its bundled snapshot so the UI renders instantly.
 * - `refresh()` attempts a live pull for each dataset with a fetcher, replacing
 *   its series on success and flipping status to 'live'. On failure the
 *   snapshot stays and status becomes 'cached'. Datasets with no live feed are
 *   'reference'.
 * - Supports an optional auto-refresh interval.
 */

function seed() {
  const out = {}
  for (const [id, snap] of Object.entries(SNAPSHOTS)) {
    out[id] = {
      ...snap,
      series: snap.series, // effective series (snapshot until a live pull lands)
      status: hasLiveSource(id) ? 'idle' : 'reference',
      error: null,
    }
  }
  return out
}

export function useClimateData() {
  const [datasets, setDatasets] = useState(seed)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [hasAttempted, setHasAttempted] = useState(false)
  const inFlight = useRef(false)

  const refresh = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    setIsRefreshing(true)

    const ids = Object.keys(SNAPSHOTS).filter(hasLiveSource)
    const results = await Promise.all(
      ids.map(async (id) => [id, await refreshDataset(id)]),
    )

    setDatasets((prev) => {
      const next = { ...prev }
      for (const [id, res] of results) {
        const base = SNAPSHOTS[id]
        if (res.status === 'live' && res.series) {
          next[id] = { ...base, series: res.series, status: 'live', error: null }
        } else {
          // Keep the snapshot; mark that the live attempt did not land.
          next[id] = { ...base, series: base.series, status: 'cached', error: res.error }
        }
      }
      return next
    })

    setLastUpdated(new Date())
    setHasAttempted(true)
    setIsRefreshing(false)
    inFlight.current = false
  }, [])

  // Kick off a live pull on first mount.
  useEffect(() => {
    refresh()
  }, [refresh])

  return {
    datasets,
    refresh,
    isRefreshing,
    lastUpdated,
    hasAttempted,
    snapshotAsOf: SNAPSHOT_AS_OF,
  }
}

// Small hook: run `cb` every `seconds` while `enabled`. Never fires while a
// refresh is already in flight (the callback guards that itself).
export function useAutoRefresh(cb, enabled, seconds) {
  const saved = useRef(cb)
  useEffect(() => {
    saved.current = cb
  }, [cb])

  useEffect(() => {
    if (!enabled) return
    const ms = Math.max(15, seconds) * 1000
    const id = setInterval(() => saved.current?.(), ms)
    return () => clearInterval(id)
  }, [enabled, seconds])
}
