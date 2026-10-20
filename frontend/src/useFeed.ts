import { useEffect, useMemo, useSyncExternalStore } from 'react'
import { MatchFeed } from './feed'

export function useFeed(matchId: string, feeds: string[] = []) {
  const key = feeds.join(',')
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const feed = useMemo(() => new MatchFeed(matchId, feeds), [matchId, key])
  useEffect(() => {
    feed.connect()
    return () => feed.close()
  }, [feed])
  const snap = useSyncExternalStore(
    (fn) => feed.subscribe(fn),
    () => feed.snapshot,
  )
  return { feed, snap }
}

export function formatClock(clock: number, period: number) {
  const base = period === 1 ? 45 * 60 : 90 * 60
  const main = Math.min(clock, base)
  const mm = Math.floor(main / 60)
  const ss = Math.floor(main % 60)
  const text = `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
  const added = clock - base
  const extra = added > 0 ? `+${Math.floor(added / 60)}:${String(Math.floor(added % 60)).padStart(2, '0')}` : null
  return { text, extra }
}

export function minuteLabel(clock: number, period: number) {
  const base = period === 1 ? 45 : 90
  const minute = Math.floor(clock / 60) + 1
  return minute > base ? `${base}+${minute - base}'` : `${minute}'`
}
