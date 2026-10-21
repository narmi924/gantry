import { useEffect, useState } from 'react'
import type { FeedSnapshot } from '../feed'
import { playerName, t } from '../i18n'
import type { FeedInfo } from '../types'

interface PlayerLine {
  player: string
  top_speed_kmh: number
  sprints: number
  distance_km: number
  passes: number
  pass_completion: number | null
  shots: number
  goals: number
}

/** The one number this viewer cares about, always in the corner of their feed. */
export function MetricBadge({ snap, info, lang }: { snap: FeedSnapshot; info: FeedInfo; lang: string }) {
  const [line, setLine] = useState<PlayerLine | null>(null)
  const tickBucket = Math.floor(snap.tick / 50)
  useEffect(() => {
    if (!info.follow || !snap.meta) return
    const ctrl = new AbortController()
    fetch(`/api/matches/${snap.meta.id}/stats?tick=${tickBucket * 50}`, { signal: ctrl.signal })
      .then((r) => r.json())
      .then((d) => setLine((d.players as PlayerLine[]).find((p) => p.player === info.follow) ?? null))
      .catch(() => {})
    return () => ctrl.abort()
  }, [tickBucket, info.follow, snap.meta])
  if (!info.metric || !snap.meta) return null
  const meta = snap.meta
  const p = meta.teams.flatMap((x) => x.players).find((x) => x.id === info.follow)
  const team = snap.stats?.teams[info.club ?? 0]
  let rows: [string, string][] = []
  if (p && line) {
    rows = {
      speed: [[t(lang, 'top_speed'), `${line.top_speed_kmh.toFixed(1)} km/h`], [t(lang, 'sprints'), String(line.sprints)]],
      distance: [[t(lang, 'distance'), `${line.distance_km.toFixed(1)} km`]],
      passing: [[t(lang, 'passes'), String(line.passes)], [t(lang, 'pass_accuracy'), line.pass_completion == null ? '–' : `${Math.round(line.pass_completion * 100)}%`]],
      shots: [[t(lang, 'shots'), `${line.shots} (${line.goals})`]],
    }[info.metric] as [string, string][]
  } else if (team) {
    rows = {
      speed: [[t(lang, 'sprints'), String(team.sprints)]],
      distance: [[t(lang, 'distance_km'), team.distance_km.toFixed(1)]],
      passing: [[t(lang, 'pass_accuracy'), team.completion == null ? '–' : `${Math.round(team.completion * 100)}%`]],
      shots: [[t(lang, 'shots'), `${team.shots} (${team.on_target})`], [t(lang, 'xg'), team.xg.toFixed(1)]],
    }[info.metric] as [string, string][]
  }
  if (!rows.length) return null
  const who = p ? playerName(snap.names, lang, p.id, p.name, true) : meta.teams[info.club ?? 0].short
  return (
    <aside className="metric" aria-label={who}>
      <b>{who}</b>
      {rows.map(([k, v]) => (
        <span key={k}>
          {k} <strong dir="ltr">{v}</strong>
        </span>
      ))}
    </aside>
  )
}
