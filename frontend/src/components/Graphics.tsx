import { useEffect, useState } from 'react'
import type { FeedSnapshot } from '../feed'
import { clubName, playerName, t } from '../i18n'
import type { MatchEvent, Meta, Player } from '../types'
import { formatClock, minuteLabel } from '../useFeed'

export function ScoreBug({ snap }: { snap: FeedSnapshot }) {
  const meta = snap.meta
  if (!meta) return null
  const [home, away] = meta.teams
  const { text, extra } = formatClock(snap.clock, snap.period)
  return (
    <div className="bug" aria-label="Score">
      <span className="bug-team">
        <i style={{ background: home.colors.shirt }} />
        {home.code}
      </span>
      <span className="bug-score">
        {snap.score[0]}
        <span className="bug-dash">–</span>
        {snap.score[1]}
      </span>
      <span className="bug-team bug-team-away">
        {away.code}
        <i style={{ background: away.colors.shirt }} />
      </span>
      <span className="bug-clock">{text}</span>
      {extra && <span className="bug-extra">{extra}</span>}
    </div>
  )
}

function playerById(meta: Meta, id?: unknown): Player | undefined {
  if (typeof id !== 'string') return undefined
  for (const t of meta.teams) {
    const p = t.players.find((x) => x.id === id)
    if (p) return p
  }
  return undefined
}

const SHOW_MS = 7000

/** Full-width lower third when a goal goes in. */
export function GoalCard({ snap, lang }: { snap: FeedSnapshot; lang: string }) {
  const [goal, setGoal] = useState<MatchEvent | null>(null)
  const latest = [...snap.events].reverse().find((e) => e.type === 'goal')
  useEffect(() => {
    if (!latest || snap.tick - latest.tick > 30) return
    setGoal(latest)
    const t = setTimeout(() => setGoal(null), SHOW_MS)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latest?.id])
  const meta = snap.meta
  if (!goal || !meta) return null
  const team = meta.teams[goal.team ?? 0]
  const scorer = playerById(meta, goal.player)
  const assist = playerById(meta, goal.assist)
  const score = goal.score as [number, number]
  return (
    <div className="goal" key={goal.id} style={{ ['--team' as string]: team.colors.shirt }}>
      <div className="goal-word">{t(lang, 'goal')}</div>
      <div className="goal-body">
        <div className="goal-scorer">
          {scorer ? playerName(snap.names, lang, scorer.id, scorer.name) : ''} <span className="goal-min" dir="ltr">{minuteLabel(goal.clock, goal.period)}</span>
        </div>
        <div className="goal-line">
          {clubName(snap.names, lang, team.code, team.name, true)}
          {assist ? `, ${t(lang, 'assisted_by', { name: playerName(snap.names, lang, assist.id, assist.name) })}` : ''}
        </div>
      </div>
      <div className="goal-score">
        {meta.teams[0].code} {score[0]}–{score[1]} {meta.teams[1].code}
      </div>
    </div>
  )
}

export function PeriodCard({ snap, lang, whistle = null }: { snap: FeedSnapshot; lang: string; whistle?: string | null }) {
  const meta = snap.meta
  const ev = snap.events[snap.events.length - 1]
  // while the picture holds at a whistle, the card shows even though the whistle itself is a tick away
  const last = whistle ? { type: whistle, tick: snap.tick } : ev
  if (!meta || !last || !['half_time', 'full_time'].includes(last.type)) return null
  if (snap.tick - last.tick > 40 && last.type === 'half_time') return null
  const [home, away] = meta.teams
  return (
    <div className="period">
      <div className="period-label">{t(lang, last.type === 'half_time' ? 'half_time' : 'full_time')}</div>
      <div className="period-score">
        <span>{clubName(snap.names, lang, home.code, home.name, true)}</span>
        <b>
          {snap.score[0]}–{snap.score[1]}
        </b>
        <span>{clubName(snap.names, lang, away.code, away.name, true)}</span>
      </div>
    </div>
  )
}
