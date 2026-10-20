import type { FeedSnapshot } from '../feed'
import { FEEDS, type TalkItem } from '../types'
import { minuteLabel } from '../useFeed'

const KIND: Record<string, string> = {
  goal: 'Goal',
  big_chance: 'Big chance',
  shot: 'Shot',
  press: 'Pressing',
  sprint: 'Sprint',
  spell: 'Read of the game',
  play: 'Play',
  corner: 'Corner',
  card: 'Card',
  substitution: 'Substitution',
  kickoff: 'Kick-off',
  half_time: 'Half-time',
  full_time: 'Full-time',
  question: 'A viewer asks',
}

interface Moment {
  tick: number
  kind: string
  asks: TalkItem[]
  desk: TalkItem[]
  director: TalkItem[]
  lines: TalkItem[]
  seconds: number | null
}

function group(items: TalkItem[]): Moment[] {
  const byTick = new Map<number, Moment>()
  for (const t of items) {
    let m = byTick.get(t.tick)
    if (!m) byTick.set(t.tick, (m = { tick: t.tick, kind: t.moment ?? 'play', asks: [], desk: [], director: [], lines: [], seconds: null }))
    if (t.moment) m.kind = t.moment
    if (t.who.startsWith('Viewer') || t.who === 'Producer') m.asks.push(t)
    else if (t.who === 'Stats desk') m.desk.push(t)
    else if (t.who === 'Director') m.director.push(t)
    else if (t.who.startsWith('Commentator')) m.lines.push(t)
    else if (t.who === 'Gallery') {
      const s = /in ([\d.]+)s/.exec(t.text)
      if (s) m.seconds = Number(s[1])
    }
  }
  return [...byTick.values()].sort((a, b) => b.tick - a.tick)
}

const feedLabel = (id: string | null) => FEEDS.find((f) => f.id === id)?.label ?? ''

/** The crew at work, one card per moment: what the desk found, what the director called, what each feed said. */
export function Talkback({ snap }: { snap: FeedSnapshot }) {
  const visible = snap.talkback.filter((t) => t.tick <= snap.tick + 5)
  const moments = group(visible).filter((m) => m.asks.length || m.desk.length || m.director.length || m.lines.length).slice(0, 4)
  return (
    <aside className="talkback" aria-label="Crew talkback">
      <header className="talkback-head">
        <span>Talkback</span>
        <span className="talkback-sub">The AI crew, 15 s ahead</span>
      </header>
      <ol className="talkback-list">
        {moments.map((m) => (
          <li key={m.tick} className="mcard">
            <div className="mcard-head">
              <span className="mcard-min">{minuteLabel(Math.max(0, snap.clock - (snap.tick - m.tick) / 10), snap.period)}</span>
              <span className="mcard-kind">{KIND[m.kind] ?? m.kind}</span>
              {m.seconds != null && <span className="mcard-time">produced in {m.seconds.toFixed(1)} s</span>}
            </div>
            {m.asks.map((t, i) => (
              <p key={`q${i}`} className="talk talk-desk"><b>{t.who.startsWith('Viewer') ? `Viewer · ${feedLabel(t.feed)}` : 'Producer'}</b> {t.text}</p>
            ))}
            {m.desk.slice(-1).map((t, i) => (
              <p key={`d${i}`} className="talk talk-desk"><b>Stats desk</b> {t.text}</p>
            ))}
            {m.director.filter((t) => t.to === 'Crew').slice(-1).map((t, i) => (
              <p key={`c${i}`} className="talk talk-director"><b>Director</b> {t.text}</p>
            ))}
            {m.director.filter((t) => t.to === 'Replay').slice(-1).map((t, i) => (
              <p key={`r${i}`} className="talk talk-director"><b>Director</b> {t.text.replace(/^replay, /, 'replay angles: ')}</p>
            ))}
            {m.lines.map((t, i) => (
              <p key={`l${i}`} className={`talk talk-commentator ${t.source !== 'ai' ? 'talk-prepared' : ''}`}>
                <b>{feedLabel(t.feed)}</b> {t.text}
              </p>
            ))}
          </li>
        ))}
        {!moments.length && <li className="talk-empty">The crew is warming up. Their calls appear here as the match plays.</li>}
      </ol>
    </aside>
  )
}
