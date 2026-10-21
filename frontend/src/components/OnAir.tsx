import { useEffect, useRef, useState } from 'react'
import type { FeedSnapshot, MatchFeed } from '../feed'
import { clubName, playerName, t, type NameSheet } from '../i18n'
import { audienceOf, languageOf, type Cue, type FeedId, type Meta, type Player } from '../types'
import { StatsPanel } from './StatsPanel'

/** ?captions=0 hides the captions, for recordings that add their own */
const CAPTIONS = !/[?&]captions=0(&|$)/.test(location.search)
const FILM = /[?&]film=/.test(location.search)

/**
 * What the selected feed puts on air: the commentator's voice and captions, and
 * the graphics the director calls. Everything arrives as timed cues from the crew.
 */
interface Props {
  feed: MatchFeed
  snap: FeedSnapshot
  /** which broadcast this layer belongs to */
  selected: FeedId
  /** whether this layer's commentary should be heard */
  sound: boolean
  /** graphics drawn in the 3D picture rather than on top of it */
  onPictureGraphic?: (cue: Cue) => void
}

export function OnAir({ feed, snap, selected, sound, onPictureGraphic }: Props) {
  const [caption, setCaption] = useState<{ id: string; text: string } | null>(null)
  const [graphic, setGraphic] = useState<Cue | null>(null)
  const audio = useRef<HTMLAudioElement | null>(null)
  const panner = useRef<{ ctx: AudioContext; pan: StereoPannerNode; routed: WeakSet<HTMLAudioElement> } | null>(null)
  const preloaded = useRef(new Map<string, HTMLAudioElement>())
  const answering = useRef(0)
  const settings = useRef({ selected, sound, speed: snap.speed, onPictureGraphic })
  settings.current = { selected, sound, speed: snap.speed, onPictureGraphic }

  // fetch upcoming lines early so they start exactly on cue
  useEffect(() => {
    const t = setInterval(() => {
      for (const c of feed.upcoming) {
        if (c.kind === 'line' && c.audio && c.feed === settings.current.selected && !preloaded.current.has(c.audio)) {
          const a = new Audio(`/api/audio/${c.audio}`)
          a.preload = 'auto'
          preloaded.current.set(c.audio, a)
        }
      }
      if (preloaded.current.size > 40) {
        const first = preloaded.current.keys().next().value
        if (first) preloaded.current.delete(first)
      }
    }, 500)
    return () => clearInterval(t)
  }, [feed])

  useEffect(() => {
    const timers: number[] = []
    const off = feed.onCue((c) => {
      const { selected, sound, speed } = settings.current
      if (c.feed !== selected) return
      if (c.kind === 'line' && c.text) {
        // an answer to the viewer's question isn't talked over, except by a big moment
        const now = performance.now()
        if (c.moment !== 'question' && now < answering.current && !c.excited) return
        if (c.moment === 'question') answering.current = now + ((c.seconds ?? 3) * 1000) / Math.max(1, speed) + 300
        setCaption({ id: c.id, text: c.text })
        const ms = ((c.seconds ?? 3) * 1000) / Math.max(1, speed) + 600
        timers.push(window.setTimeout(() => setCaption((cur) => (cur?.id === c.id ? null : cur)), ms))
        if (sound && speed <= 1.25 && c.audio) {
          audio.current?.pause()
          const a = preloaded.current.get(c.audio) ?? new Audio(`/api/audio/${c.audio}`)
          audio.current = a
          // the audio-described feed's voice comes from where the ball is, left to right
          if (audienceOf(selected) === 'audio') {
            panner.current ??= (() => {
              const ctx = new AudioContext()
              const pan = ctx.createStereoPanner()
              pan.connect(ctx.destination)
              return { ctx, pan, routed: new WeakSet<HTMLAudioElement>() }
            })()
            const p = panner.current
            if (!p.routed.has(a)) {
              p.ctx.createMediaElementSource(a).connect(p.pan)
              p.routed.add(a)
            }
            p.ctx.resume().catch(() => {})
          }
          a.currentTime = 0
          a.play().catch(() => {})
          // a log of what went on air, used when exporting a clip with sound
          const w = window as unknown as { __gantryAired?: unknown[] }
          ;(w.__gantryAired ??= []).push({ t: performance.now(), audio: c.audio, text: c.text, feed: c.feed })
        }
      } else if (c.kind === 'graphic' && c.graphic?.type === 'pitch') {
        settings.current.onPictureGraphic?.(c)
      } else if (c.kind === 'graphic' && c.graphic) {
        setGraphic(c)
        const ms = (c.graphic.seconds * 1000) / Math.max(1, speed)
        timers.push(window.setTimeout(() => setGraphic((cur) => (cur?.id === c.id ? null : cur)), ms))
      }
    })
    return () => {
      off()
      timers.forEach(clearTimeout)
    }
  }, [feed])

  useEffect(() => {
    const t = setInterval(() => {
      const p = panner.current
      const s = feed.sample()
      if (!p || !s) return
      const x = Math.max(-1, Math.min(1, (s.ball[0] - 52.5) / 52.5))
      p.pan.pan.setTargetAtTime(x * 0.85, p.ctx.currentTime, 0.25)
      // kept with the log of what went on air, so an exported clip pans the same way
      if (FILM) {
        const w = window as unknown as { __gantryPan?: unknown[] }
        ;(w.__gantryPan ??= []).push({ t: performance.now(), x: x * 0.85 })
      }
    }, 100)
    return () => clearInterval(t)
  }, [feed])

  // switching feed or muting stops the voice of the old one
  useEffect(() => {
    audio.current?.pause()
    setCaption(null)
    setGraphic(null)
  }, [selected])
  useEffect(() => {
    if (!sound) audio.current?.pause()
  }, [sound])

  const meta = snap.meta
  const lang = languageOf(selected)
  return (
    <>
      {graphic?.graphic?.type === 'stats' && <StatsPanel snap={snap} lang={lang} />}
      {graphic?.graphic?.type === 'momentum' && <MomentumCard snap={snap} lang={lang} />}
      {graphic?.graphic?.type === 'player' && meta && <PlayerCard meta={meta} cue={graphic} lang={lang} names={snap.names} />}
      {graphic?.graphic?.type === 'lineups' && meta && <LineupsCard meta={meta} lang={lang} names={snap.names} />}
      {CAPTIONS && caption && (
        <div className="caption" key={caption.id} aria-live="polite">
          {caption.text}
        </div>
      )}
    </>
  )
}

function MomentumCard({ snap, lang }: { snap: FeedSnapshot; lang: string }) {
  const meta = snap.meta
  const series = snap.stats?.momentum.slice(-15) ?? []
  if (!meta || !series.length) return null
  const [h, a] = meta.teams
  return (
    <section className="panel panel-narrow" aria-label="Attack momentum">
      <header className="panel-head">
        <span className="key"><i className="swatch swatch-home" />{h.code}</span>
        <span className="panel-title">{t(lang, 'who_is_on_top')}</span>
        <span className="key">{a.code}<i className="swatch swatch-away" /></span>
      </header>
      <div className="mom-plot mom-plot-tall" role="img" aria-label={`Attack momentum, last ${series.length} minutes; above the line ${h.short}, below ${a.short}`}>
        {series.map((m) => (
          <div key={m.minute} className="mom-col" title={`${m.minute}'`}>
            <i className={`mom-bar mom-${m.value >= 0 ? 'home' : 'away'}`} style={{ height: `${Math.max(Math.abs(m.value) * 100, 2) / 2}%` }} />
          </div>
        ))}
      </div>
      <div className="mom-axis">
        <span>{series[0].minute}'</span>
        <span>{series[series.length - 1].minute}'</span>
      </div>
    </section>
  )
}

/** Both starting elevens before kick-off, in the feed's language. */
function LineupsCard({ meta, lang, names }: { meta: Meta; lang: string; names: NameSheet }) {
  return (
    <section className="lineups" aria-label={t(lang, 'lineups')}>
      <header className="lineups-head">{t(lang, 'lineups')}</header>
      <div className="lineups-cols">
        {meta.teams.map((team) => (
          <div key={team.code} className="lineups-team" style={{ ['--team' as string]: team.colors.shirt }}>
            <div className="lineups-club">
              <i />
              {clubName(names, lang, team.code, team.name, true)}
              <span dir="ltr">{team.formation}</span>
            </div>
            <ol>
              {team.starters.map((id) => {
                const p = team.players.find((x) => x.id === id)!
                return (
                  <li key={id}>
                    <b>{p.number}</b>
                    {playerName(names, lang, p.id, p.name)}
                  </li>
                )
              })}
            </ol>
          </div>
        ))}
      </div>
    </section>
  )
}

function PlayerCard({ meta, cue, lang, names }: { meta: Meta; cue: Cue; lang: string; names: NameSheet }) {
  const id = cue.graphic?.player
  let player: Player | undefined
  let teamIdx = 0
  meta.teams.forEach((t, i) => {
    const p = t.players.find((x) => x.id === id)
    if (p) {
      player = p
      teamIdx = i
    }
  })
  const prof = (cue.graphic?.profile ?? {}) as Record<string, number | null>
  if (!player) return null
  const team = meta.teams[teamIdx]
  const completion = prof.pass_completion_pct ?? (prof.pass_completion != null ? Math.round((prof.pass_completion as number) * 100) : null)
  const rows: [string, string][] = [
    [t(lang, 'distance'), `${(prof.distance_km ?? 0).toFixed(1)} km`],
    [t(lang, 'top_speed'), `${(prof.top_speed_kmh ?? 0).toFixed(1)} km/h`],
    [t(lang, 'sprints'), String(prof.sprints ?? 0)],
    [t(lang, 'passes'), completion != null ? `${prof.passes}, ${completion}%` : String(prof.passes ?? 0)],
  ]
  if (prof.goals || prof.assists) rows.push([t(lang, 'goals_assists'), `${prof.goals ?? 0}, ${prof.assists ?? 0}`])
  return (
    <section className="pcard" aria-label={playerName(names, lang, player.id, player.name)} style={{ ['--team' as string]: team.colors.shirt }}>
      <div className="pcard-num">{player.number}</div>
      <div className="pcard-body">
        <div className="pcard-name">{playerName(names, lang, player.id, player.name)}</div>
        <div className="pcard-sub">{clubName(names, lang, team.code, team.name, true)}</div>
        <dl className="pcard-stats">
          {rows.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  )
}
