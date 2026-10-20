import type { FeedSnapshot } from '../feed'
import type { TeamStats } from '../types'

type Row = { label: string; value: (t: TeamStats) => string }

const pct = (v: number | null) => (v == null ? '–' : `${Math.round(v * 100)}%`)

const ROWS: Row[] = [
  { label: 'Shots (on target)', value: (t) => `${t.shots} (${t.on_target})` },
  { label: 'Expected goals', value: (t) => t.xg.toFixed(1) },
  { label: 'Pass accuracy', value: (t) => pct(t.completion) },
  { label: 'Field tilt', value: (t) => pct(t.field_tilt) },
  { label: 'Pressing (PPDA)', value: (t) => (t.ppda == null ? '–' : t.ppda.toFixed(1)) },
  { label: 'Distance (km)', value: (t) => t.distance_km.toFixed(1) },
  { label: 'Sprints', value: (t) => String(t.sprints) },
  { label: 'Corners', value: (t) => String(t.corners) },
]

/** Head-to-head numbers and the attack momentum chart, as a broadcast data panel. */
export function StatsPanel({ snap }: { snap: FeedSnapshot }) {
  const meta = snap.meta
  const stats = snap.stats
  if (!meta || !stats) return null
  const [home, away] = stats.teams
  const [hTeam, aTeam] = meta.teams
  const hp = Math.round(home.possession * 100)
  return (
    <section className="panel" aria-label="Match statistics">
      <header className="panel-head">
        <span className="key"><i className="swatch swatch-home" />{hTeam.code}</span>
        <span className="panel-title">Match stats</span>
        <span className="key">{aTeam.code}<i className="swatch swatch-away" /></span>
      </header>

      <div className="poss">
        <div className="poss-nums">
          <b>{hp}%</b>
          <span>Possession</span>
          <b>{100 - hp}%</b>
        </div>
        <div className="poss-bar" role="img" aria-label={`Possession ${hp}% to ${100 - hp}%`}>
          <i className="poss-home" style={{ width: `${hp}%` }} />
          <i className="poss-away" style={{ width: `${100 - hp}%` }} />
        </div>
      </div>

      <table className="h2h">
        <tbody>
          {ROWS.map((r) => (
            <tr key={r.label}>
              <td>{r.value(home)}</td>
              <th scope="row">{r.label}</th>
              <td>{r.value(away)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <Momentum series={stats.momentum} homeName={hTeam.short} awayName={aTeam.short} />
    </section>
  )
}

function Momentum({ series, homeName, awayName }: { series: { minute: number; value: number }[]; homeName: string; awayName: string }) {
  const minutes = series.slice(-20)
  return (
    <figure className="mom">
      <figcaption>Attack momentum, last {minutes.length} minutes</figcaption>
      <div className="mom-plot" role="img" aria-label={`Attack momentum by minute; above the line ${homeName}, below ${awayName}`}>
        {minutes.map((m) => {
          const h = Math.round(Math.abs(m.value) * 100)
          const side = m.value >= 0 ? 'home' : 'away'
          const who = m.value >= 0 ? homeName : awayName
          return (
            <div key={m.minute} className="mom-col" title={`${m.minute}' · ${h === 0 ? 'quiet' : `${who} on top`}`}>
              <i className={`mom-bar mom-${side}`} style={{ height: `${Math.max(h, 2) / 2}%` }} />
            </div>
          )
        })}
      </div>
      <div className="mom-axis">
        <span>{minutes[0]?.minute}'</span>
        <span>{minutes[minutes.length - 1]?.minute}'</span>
      </div>
    </figure>
  )
}
