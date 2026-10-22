import { useEffect, useState } from 'react'
import type { FeedSnapshot, MatchFeed } from '../feed'
import { AUDIENCE_LABEL, audienceOf, type Cue } from '../types'

/** What the crew has already made and the viewers haven't seen yet: the broadcast delay, made visible. */
export function Rundown({ feed, snap }: { feed: MatchFeed; snap: FeedSnapshot }) {
  const [, setNow] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setNow((n) => n + 1), 400)
    return () => clearInterval(t)
  }, [])
  const tick = feed.renderTick
  const speed = Math.max(1, snap.speed)
  const next = feed.upcoming.filter((c) => c.tick >= tick && c.kind !== 'reel').slice(0, 9)
  const name = (id: string) => snap.feeds.find((f) => f.id === id)?.name ?? AUDIENCE_LABEL[audienceOf(id)]
  return (
    <ol className="rundown-list">
      {next.map((c) => (
        <li key={c.id} className={`rundown-item rundown-${c.kind}`}>
          <span className="rundown-in">{((c.tick - tick) / 10 / speed).toFixed(0)} s</span>
          <span className="rundown-what">
            <b>{c.feed === '*' ? 'All feeds' : name(c.feed)}</b>
            {describe(c)}
          </span>
        </li>
      ))}
      {!next.length && <li className="talk-empty">Nothing booked yet. The crew books each moment about 15 seconds before it airs.</li>}
    </ol>
  )
}

const ANGLES: Record<string, string> = {
  behind_goal: 'Replay from behind the goal',
  high: 'Replay from the high camera',
  follow: 'Replay, following the ball',
  reverse: 'Replay from the reverse angle',
}
const GRAPHICS: Record<string, string> = {
  player: 'Player card', stats: 'Match stats', momentum: 'Who is on top', pitch: 'Space on the pitch', lineups: 'Line-ups',
}

function describe(c: Cue): string {
  if (c.kind === 'line') return c.text ?? ''
  if (c.kind === 'replay') return ANGLES[c.replay?.angle ?? ''] ?? 'Replay'
  if (c.kind === 'graphic') return `Graphic: ${GRAPHICS[c.graphic?.type ?? ''] ?? c.graphic?.type}`
  if (c.kind === 'reel') return 'Highlights'
  return c.kind
}
