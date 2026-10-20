import { useEffect, useRef, useState } from 'react'
import type { FeedSnapshot, MatchFeed } from '../feed'
import { Broadcast3D, type ViewSpec } from '../three/broadcast3d'
import type { CameraMode } from '../three/cameras'
import { Labels } from '../three/labels'
import { L } from '../three/world'
import { FEEDS, type Cue, type FeedId, type FeedReport, type Player, type ReelLine, type ReplayAngle } from '../types'
import { QuestionCard } from './AskBox'
import { GoalCard, PeriodCard, ScoreBug } from './Graphics'
import { OnAir } from './OnAir'
import { ReportCard } from './ReportCard'
import { StatsPanel } from './StatsPanel'

export type Layout = 'single' | 'wall'

/** How each broadcast is filmed by default. */
const FEED_CAMERA: Record<FeedId, { mode: CameraMode; analyst: boolean }> = {
  casual_en: { mode: 'broadcast', analyst: false },
  analyst_en: { mode: 'broadcast', analyst: true },
  home_zh: { mode: 'follow', analyst: false },
  audio_en: { mode: 'broadcast', analyst: false },
}

const FOLLOWED: Partial<Record<FeedId, string>> = { home_zh: 'KSM-10' }

interface Segment {
  from: number
  to: number
  speed: number
  focus: string | null
  team: number | null
  angles: Map<FeedId, ReplayAngle>
  lines?: Record<string, ReelLine>
}

/** A replay (one segment) or a highlights package (several), played on its own clock. */
interface Playback {
  key: number
  kind: 'replay' | 'reel'
  segments: Segment[]
  index: number
  startedAt: number | null
  requested: boolean
  reports?: Record<string, FeedReport>
  resume?: boolean
  when?: 'half_time' | 'full_time'
  askedAt?: number
}

interface Props {
  feed: MatchFeed
  snap: FeedSnapshot
  layout: Layout
  selected: FeedId
  onSelect: (f: FeedId) => void
  sound: boolean
  tactical: boolean
  showStats: boolean
}

export function Stage({ feed, snap, layout, selected, onSelect, sound, tactical, showStats }: Props) {
  const glRef = useRef<HTMLCanvasElement>(null)
  const tagRef = useRef<HTMLCanvasElement>(null)
  const tileRefs = useRef(new Map<FeedId, HTMLDivElement>())
  const view = useRef<Broadcast3D | null>(null)
  const replay = useRef<Playback | null>(null)
  const [replaying, setReplaying] = useState<null | 'replay' | 'reel'>(null)
  const [reports, setReports] = useState<Record<string, FeedReport> | null>(null)
  // at the half-time whistle the picture holds for the editor's package
  const halfTimeHold = useRef<{ tick: number; timer: number } | null>(null)
  const handledWhistle = useRef(-1)

  useEffect(() => {
    const last = snap.events[snap.events.length - 1]
    if (!last || last.type !== 'half_time' || last.tick === handledWhistle.current) return
    handledWhistle.current = last.tick
    if (snap.speed > 1.25 || !snap.playing) return
    feed.setPlaying(false)
    const timer = window.setTimeout(() => {
      // no package came: carry on with the second half
      if (halfTimeHold.current) {
        halfTimeHold.current = null
        feed.setPlaying(true)
      }
    }, 35000)
    halfTimeHold.current = { tick: last.tick, timer }
  }, [snap.events, snap.speed, snap.playing, feed])
  const props = useRef({ snap, layout, selected, tactical })
  props.current = { snap, layout, selected, tactical }

  const feeds: FeedId[] = layout === 'wall' ? FEEDS.map((f) => f.id) : [selected]

  // the director calls replays, the editor calls highlights; every feed goes together, each from its own angle
  useEffect(() => {
    const off = feed.onCue((c: Cue) => {
      if (feed.snapshot.speed > 1.25) return
      if (c.kind === 'reel' && c.reel && c.reel.clips.length) {
        const reel = c.reel
        const half = reel.when === 'half_time'
        const held = halfTimeHold.current
        if (held) {
          window.clearTimeout(held.timer)
          halfTimeHold.current = null
        }
        const resume = half && (held !== null || feed.snapshot.playing)
        if (half) feed.setPlaying(false) // the half-time show
        replay.current = {
          key: c.tick, kind: 'reel', index: 0, startedAt: null, requested: false, reports: reel.reports, resume, when: reel.when,
          segments: reel.clips.map((clip) => {
            const natural = (clip.to - clip.from) / 10
            const longest = Math.max(0, ...Object.values(clip.lines).map((l) => l.seconds))
            return {
              from: clip.from, to: clip.to, focus: clip.focus, team: clip.team, lines: clip.lines,
              speed: Math.max(0.4, Math.min(0.9, natural / (longest + 0.8))),
              angles: new Map(Object.entries(clip.angles) as [FeedId, ReplayAngle][]),
            }
          }),
        }
        return
      }
      if (c.kind !== 'replay' || !c.replay) return
      const r = c.replay
      const cur = replay.current
      if (cur?.kind === 'reel') return
      if (cur && cur.key === c.tick) {
        cur.segments[0].angles.set(c.feed as FeedId, r.angle)
        return
      }
      replay.current = {
        key: c.tick, kind: 'replay', index: 0, startedAt: null, requested: false,
        segments: [{ from: r.from, to: r.to, speed: r.speed, focus: r.focus, team: r.team, angles: new Map([[c.feed as FeedId, r.angle]]) }],
      }
    })
    return () => {
      off()
    }
  }, [feed])

  useEffect(() => {
    const gl = glRef.current!
    const tags = tagRef.current!
    const ctx = tags.getContext('2d')!
    const v = new Broadcast3D(gl)
    view.current = v
    const labels = new Map<string, Labels>()
    let raf = 0
    let last = performance.now()
    let size = ''
    let wasReplaying = false
    let segmentKey = ''
    const frame = (now: number) => {
      raf = requestAnimationFrame(frame)
      const dt = Math.min(0.1, (now - last) / 1000)
      last = now
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const w = gl.clientWidth
      const h = gl.clientHeight
      if (`${w}x${h}x${dpr}` !== size) {
        size = `${w}x${h}x${dpr}`
        v.resize(w, h, dpr)
        tags.width = Math.round(w * dpr)
        tags.height = Math.round(h * dpr)
      }
      const { snap: s, layout: lay, selected: sel, tactical: tac } = props.current
      const meta = s.meta
      const lineup = meta ? (() => {
        const byId = new Map<string, Player>()
        for (const t of meta.teams) for (const p of t.players) byId.set(p.id, p)
        return s.lineup.map((id) => byId.get(id))
      })() : []

      feed.advance(dt * 1000)

      // replays and highlights: fetch the frames, then play each segment back on its own clock
      const pb = replay.current
      let replayTick: number | null = null
      let r: Segment | null = null
      if (pb) {
        if (!pb.requested) {
          pb.requested = true
          pb.askedAt = now
          for (const seg of pb.segments) feed.requestClip(seg.from, seg.to)
        }
        r = pb.segments[pb.index]
        // if a clip still hasn't arrived after a couple of seconds, ask again
        if (pb.startedAt === null && !feed.hasFrames(r.from, r.to) && now - (pb.askedAt ?? now) > 2500) {
          pb.askedAt = now
          feed.requestClip(r.from, r.to)
        }
        if (pb.startedAt === null && feed.hasFrames(r.from, r.to)) {
          pb.startedAt = now
          // each feed's narration for this clip goes on air as the clip starts
          for (const [feedId, line] of Object.entries(r.lines ?? {})) {
            feed.inject({ id: `reel-${pb.key}-${pb.index}-${feedId}`, feed: feedId, tick: feed.renderTick, kind: 'line', moment: 'highlights', text: line.text, audio: line.audio, seconds: line.seconds, source: 'ai' })
          }
        }
        if (pb.startedAt !== null) {
          replayTick = r.from + ((now - pb.startedAt) / 100) * r.speed
          if (replayTick >= r.to) {
            pb.index += 1
            pb.startedAt = null
            replayTick = null
            if (pb.index >= pb.segments.length) {
              replay.current = null
              feed.unpinAll()
              if (pb.kind === 'reel' && pb.reports) {
                setReports(pb.reports)
                // at half-time the report stays up for a while, then the second half resumes;
                // at full-time it stays
                if (pb.when === 'half_time') {
                  const resume = pb.resume
                  window.setTimeout(() => {
                    setReports(null)
                    if (resume) feed.setPlaying(true)
                  }, 14000)
                }
              }
            } else replayTick = pb.segments[pb.index].from
          }
        }
        if (replay.current) r = replay.current.segments[replay.current.index]
      }
      const inReplay = replayTick !== null
      const sample = inReplay ? feed.sampleAt(replayTick!) : feed.sample()
      const events = inReplay ? s.events.filter((e) => e.tick <= replayTick!) : s.events
      const key = inReplay && pb ? `${pb.key}-${pb.index}` : ''
      if (key !== segmentKey) {
        setReplaying(inReplay && pb ? pb.kind : null)
        if (inReplay && r && meta) v.replay.start(meta.teams[r.team ?? 0].colors.shirt)
        else v.replay.stop()
      }

      // one camera per broadcast on screen, each in its tile
      const origin = gl.getBoundingClientRect()
      const ids: FeedId[] = lay === 'wall' ? FEEDS.map((f) => f.id) : [sel]
      const focusSlot = r?.focus ? s.lineup.indexOf(r.focus) : -1
      const specs: ViewSpec[] = ids.map((id) => {
        const el = tileRefs.current.get(id)
        const rect = el?.getBoundingClientRect()
        const cam = FEED_CAMERA[id]
        const followId = FOLLOWED[id]
        const angle = inReplay ? r!.angles.get(id) ?? 'high' : null
        return {
          id,
          mode: angle ?? (lay === 'single' && tac ? 'tactical' : cam.mode),
          analyst: cam.analyst,
          follow: angle === 'follow' ? focusSlot : followId ? s.lineup.indexOf(followId) : -1,
          rect: rect ? { x: rect.left - origin.left, y: rect.top - origin.top, w: rect.width, h: rect.height } : { x: 0, y: 0, w, h },
        }
      })
      let goalX: number | undefined
      if (inReplay && sample && r) {
        const forward = ((r.team ?? 0) === 0) === (sample.period === 1)
        goalX = forward ? L : 0
      }
      // into, between and out of replays is a cut, not a camera move
      v.setViews(specs, now, key !== segmentKey || inReplay !== wasReplaying, goalX)
      wasReplaying = inReplay
      segmentKey = key

      if (!meta) {
        v.frame(null, null, dt, now)
        return
      }
      if (inReplay && r) v.replay.update(r.from, replayTick!, focusSlot, (t) => feed.sampleAt(t), events, r.team)
      const goal = [...events].reverse().find((e) => e.type === 'goal')
      v.frame(sample, {
        teams: meta.teams, lineup, events,
        goal: goal && sample ? { team: goal.team ?? 0, age: (sample.tick - goal.tick) / 10 } : null,
      }, dt, now)
      ctx.clearRect(0, 0, tags.width, tags.height)
      for (const vw of v.views) {
        let l = labels.get(vw.spec.id)
        if (!l) labels.set(vw.spec.id, (l = new Labels()))
        l.draw(ctx, vw, sample, lineup, meta.teams, events, now, dpr, vw.spec.analyst ? v.telestration.lastPass : null)
      }
    }
    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      v.dispose()
      view.current = null
    }
  }, [feed])

  const showSpace = (seconds: number) => view.current?.telestration.showSpace(seconds, performance.now())

  return (
    <div className={`stage stage-${layout}`}>
      <canvas ref={glRef} className="stage-canvas" />
      <canvas ref={tagRef} className="stage-canvas stage-tags" />
      <div className={layout === 'wall' ? 'wall' : 'single'}>
        {feeds.map((id) => {
          const info = FEEDS.find((f) => f.id === id)!
          const listening = id === selected
          return (
            <div
              key={id}
              ref={(el) => {
                if (el) tileRefs.current.set(id, el)
                else tileRefs.current.delete(id)
              }}
              className={`tile ${id === 'audio_en' ? 'tile-audio' : ''} ${layout === 'wall' && listening ? 'tile-listening' : ''}`}
              onClick={layout === 'wall' ? () => onSelect(id) : undefined}
            >
              {id === 'audio_en' && <div className="audio-veil" aria-hidden />}
              {replaying && <div className="wipe" key={`wipe-${replaying}-${replay.current?.index ?? 0}`} aria-hidden />}
              <div className="safe">
                <ScoreBug snap={snap} />
                <span className="feedtag">
                  {layout === 'wall' ? info.label : `Your feed: ${info.label}`}
                  {layout === 'wall' && listening && sound && <b className="listening"> · listening</b>}
                </span>
                {replaying && <span className="replay-bug">{replaying === 'reel' ? 'Highlights' : 'Replay'}</span>}
                {reports?.[id] && snap.meta && <ReportCard report={reports[id]} meta={snap.meta} zh={id === 'home_zh'} score={snap.score} />}
                <QuestionCard snap={snap} feedId={id} />
                <GoalCard snap={snap} />
                {replaying !== 'reel' && !reports && <PeriodCard snap={snap} />}
                {layout === 'single' && showStats && <StatsPanel snap={snap} />}
                <OnAir
                  feed={feed}
                  snap={snap}
                  selected={id}
                  sound={sound && listening}
                  onPictureGraphic={id === 'analyst_en' ? (c) => showSpace(c.graphic?.seconds ?? 9) : undefined}
                />
              </div>
            </div>
          )
        })}
      </div>
      {!snap.connected && <div className="stage-note">Connecting to the match feed…</div>}
    </div>
  )
}
