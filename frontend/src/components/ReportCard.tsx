import type { FeedSnapshot } from '../feed'
import { clubName, playerName, t } from '../i18n'
import type { FeedReport } from '../types'

/** The editor's half-time or full-time report, written for this feed, in its language. */
export function ReportCard({ report, snap, lang }: { report: FeedReport; snap: FeedSnapshot; lang: string }) {
  const meta = snap.meta!
  const [home, away] = meta.teams
  let star: { name: string; number: number; color: string } | null = null
  for (const team of meta.teams) {
    const p = team.players.find((x) => x.id === report.star)
    if (p) star = { name: playerName(snap.names, lang, p.id, p.name), number: p.number, color: team.colors.shirt }
  }
  return (
    <section className="report" aria-label={report.headline}>
      <div className="report-score">
        <span><i style={{ background: home.colors.shirt }} />{clubName(snap.names, lang, home.code, home.short)}</span>
        <b dir="ltr">{snap.score[0]}–{snap.score[1]}</b>
        <span>{clubName(snap.names, lang, away.code, away.short)}<i style={{ background: away.colors.shirt }} /></span>
      </div>
      <h2 className="report-head">{report.headline}</h2>
      <p className="report-body">{report.summary}</p>
      {star && (
        <div className="report-star">
          <span className="report-star-num" style={{ background: star.color }}>{star.number}</span>
          <span>
            <small>{t(lang, 'player_of_the_match')}</small>
            {star.name}
          </span>
        </div>
      )}
    </section>
  )
}
