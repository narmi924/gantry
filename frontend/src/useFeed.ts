import { useEffect, useMemo, useRef, useSyncExternalStore } from 'react'
import { MatchFeed } from './feed'

export function useFeed(matchId: string, feeds: string[] = []) {
  const key = feeds.join(',')
  const previous = useRef<MatchFeed | null>(null)
  // a new set of feeds is a new connection; it picks up where the old one was
  const feed = useMemo(() => {
    const resume = previous.current ? Math.round(previous.current.renderTick) : null
    return new MatchFeed(matchId, feeds, resume)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchId, key])
  previous.current = feed
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
