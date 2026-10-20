import type { FeedSnapshot, MatchFeed } from '../feed'
import type { Layout } from './Stage'
import { FEEDS, type FeedId } from '../types'

const SPEEDS = [1, 2, 4, 8, 16]

interface Props {
  feed: MatchFeed
  snap: FeedSnapshot
  tactical: boolean
  onTactical: (v: boolean) => void
  layout: Layout
  showStats: boolean
  onStats: (v: boolean) => void
  selected: FeedId
  onSelect: (f: FeedId) => void
  sound: boolean
  onSound: (v: boolean) => void
}

export function Controls({ feed, snap, tactical, onTactical, layout, showStats, onStats, selected, onSelect, sound, onSound }: Props) {
  const meta = snap.meta
  const total = meta?.frames ?? 1
  const goals = snap.events.filter((e) => e.type === 'goal')

  const seekFromPointer = (e: React.PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width))
    feed.seek(f * (total - 1))
  }

  return (
    <>
    <div className="feeds" role="group" aria-label="Choose your broadcast">
      {FEEDS.map((f, i) => (
        <button key={f.id} className="feed-btn" aria-pressed={selected === f.id} onClick={() => onSelect(f.id)}>
          <span className="feed-key">{i + 1}</span>
          {f.label}
        </button>
      ))}
      <button className="toggle sound" aria-pressed={sound} onClick={() => onSound(!sound)}>
        {sound ? 'Commentary on' : 'Turn on commentary'}
      </button>
    </div>
    <div className="controls">
      <button
        className="play"
        onClick={() => feed.setPlaying(!snap.playing)}
        aria-label={snap.playing ? 'Pause' : 'Play'}
      >
        {snap.playing ? (
          <svg viewBox="0 0 16 16" aria-hidden><rect x="3" y="2" width="3.5" height="12" rx="1" /><rect x="9.5" y="2" width="3.5" height="12" rx="1" /></svg>
        ) : (
          <svg viewBox="0 0 16 16" aria-hidden><path d="M4 2.5v11l9.5-5.5z" /></svg>
        )}
      </button>

      <div className="seg" role="group" aria-label="Playback speed">
        {SPEEDS.map((s) => (
          <button key={s} aria-pressed={snap.speed === s} onClick={() => feed.setSpeed(s)}>
            {s}×
          </button>
        ))}
      </div>

      <div className="timeline" onPointerDown={seekFromPointer} role="slider" aria-label="Match timeline"
        aria-valuemin={0} aria-valuemax={total} aria-valuenow={snap.tick}>
        {meta?.periods.map((p) => (
          <div key={p.period} className="timeline-half"
            style={{ left: `${(p.start_tick / total) * 100}%`, width: `${((p.end_tick - p.start_tick) / total) * 100}%` }} />
        ))}
        <div className="timeline-played" style={{ width: `${(snap.tick / total) * 100}%` }} />
        {goals.map((g) => (
          <span key={g.id} className="timeline-goal" title="Goal"
            style={{ left: `${(g.tick / total) * 100}%`, background: meta?.teams[g.team ?? 0].colors.shirt }} />
        ))}
        <span className="timeline-head" style={{ left: `${(snap.tick / total) * 100}%` }} />
      </div>

      {layout === 'single' && (
        <>
          <button className="toggle" aria-pressed={showStats} onClick={() => onStats(!showStats)}>
            Stats
          </button>
          <div className="seg" role="group" aria-label="Camera">
            <button aria-pressed={!tactical} onClick={() => onTactical(false)}>Feed camera</button>
            <button aria-pressed={tactical} onClick={() => onTactical(true)}>Tactical</button>
          </div>
        </>
      )}
    </div>
    </>
  )
}
