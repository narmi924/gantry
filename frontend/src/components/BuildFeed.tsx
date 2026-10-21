import { useState } from 'react'
import { LANGUAGE_NAMES, type Lang } from '../i18n'
import type { Meta } from '../types'

type Style = 'casual' | 'analyst' | 'home' | 'audio'

const STYLES: { id: Style; name: string; note: string }[] = [
  { id: 'casual', name: 'New to football', note: 'Plain words, why it matters' },
  { id: 'analyst', name: 'Analyst', note: 'The tactics and the numbers' },
  { id: 'home', name: 'Supporter', note: 'On your side, every kick' },
  { id: 'audio', name: 'Audio described', note: 'For listening without the picture' },
]

const METRICS: { id: string; name: string }[] = [
  { id: '-', name: 'None' },
  { id: 'speed', name: 'Pace' },
  { id: 'distance', name: 'Distance' },
  { id: 'passing', name: 'Passing' },
  { id: 'shots', name: 'Shooting' },
]

/** A viewer builds their own broadcast: who it is for, which club, which player, which language, which number. */
export function BuildFeed({ meta, onBuild, onClose }: { meta: Meta; onBuild: (feedId: string) => void; onClose: () => void }) {
  const [style, setStyle] = useState<Style>('home')
  const [club, setClub] = useState<string>('ASH')
  const [player, setPlayer] = useState<string>('ASH-7')
  const [lang, setLang] = useState<Lang>('es')
  const [metric, setMetric] = useState<string>('speed')

  const clubFor = style === 'home' ? club : style === 'casual' ? club : '-'
  const id = `${style}_${lang}.${clubFor}.${player}.${metric}`
  const players = meta.teams.flatMap((t) => t.players.map((p) => ({ ...p, club: t.short })))
  const followed = players.find((p) => p.id === player)

  return (
    <div className="build" role="dialog" aria-modal="true" aria-labelledby="build-title">
      <form
        className="build-card"
        onSubmit={(e) => {
          e.preventDefault()
          onBuild(id)
        }}
      >
        <header className="build-head">
          <h2 id="build-title">Build your feed</h2>
          <button type="button" className="build-close" onClick={onClose} aria-label="Close">×</button>
        </header>
        <p className="build-intro">The same crew makes it for you, live, alongside the other broadcasts.</p>

        <fieldset className="build-styles">
          <legend>Who is it for</legend>
          {STYLES.map((s) => (
            <label key={s.id} className={`build-style ${style === s.id ? 'on' : ''}`}>
              <input type="radio" name="style" value={s.id} checked={style === s.id} onChange={() => setStyle(s.id)} />
              <b>{s.name}</b>
              <span>{s.note}</span>
            </label>
          ))}
        </fieldset>

        <div className="build-row">
          {(style === 'home' || style === 'casual') && (
            <label>
              <span>Your club</span>
              <select value={club} onChange={(e) => setClub(e.target.value)}>
                {style === 'casual' && <option value="-">No side</option>}
                {meta.teams.map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
              </select>
            </label>
          )}
          <label>
            <span>Follow a player</span>
            <select value={player} onChange={(e) => setPlayer(e.target.value)}>
              <option value="-">Nobody in particular</option>
              {meta.teams.map((t) => (
                <optgroup key={t.code} label={t.name}>
                  {t.players.map((p) => <option key={p.id} value={p.id}>{p.number} {p.name}</option>)}
                </optgroup>
              ))}
            </select>
          </label>
          <label>
            <span>Language</span>
            <select value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
              {(Object.keys(LANGUAGE_NAMES) as Lang[]).map((l) => <option key={l} value={l}>{LANGUAGE_NAMES[l]}</option>)}
            </select>
          </label>
          <label>
            <span>The number you care about</span>
            <select value={metric} onChange={(e) => setMetric(e.target.value)}>
              {METRICS.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </label>
        </div>

        <footer className="build-foot">
          <span className="build-summary">
            {STYLES.find((s) => s.id === style)?.name}
            {clubFor !== '-' ? `, ${meta.teams.find((t) => t.code === clubFor)?.short} fan` : ''}
            {followed ? `, following ${followed.name}` : ''}
            {`, in ${LANGUAGE_NAMES[lang]}`}
          </span>
          <button type="submit" className="build-go">Start my feed</button>
        </footer>
      </form>
    </div>
  )
}
