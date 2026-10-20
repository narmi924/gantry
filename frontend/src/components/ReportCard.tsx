import type { FeedReport, Meta } from '../types'

/** The editor's half-time or full-time report, written for this feed. */
export function ReportCard({ report, meta, zh, score }: { report: FeedReport; meta: Meta; zh: boolean; score: [number, number] }) {
  const [home, away] = meta.teams
  let star: { name: string; number: number; color: string } | null = null
  for (const t of meta.teams) {
    const p = t.players.find((x) => x.id === report.star)
    if (p) star = { name: p.name, number: p.number, color: t.colors.shirt }
  }
  return (
    <section className={`report ${zh ? 'report-zh' : ''}`} aria-label="Match report">
      <div className="report-score">
        <span><i style={{ background: home.colors.shirt }} />{home.short}</span>
        <b>{score[0]}–{score[1]}</b>
        <span>{away.short}<i style={{ background: away.colors.shirt }} /></span>
      </div>
      <h2 className="report-head">{report.headline}</h2>
      <p className="report-body">{report.summary}</p>
      {star && (
        <div className="report-star">
          <span className="report-star-num" style={{ background: star.color }}>{star.number}</span>
          <span>
            <small>{zh ? '本场最佳' : 'Player of the match'}</small>
            {star.name}
          </span>
        </div>
      )}
    </section>
  )
}
