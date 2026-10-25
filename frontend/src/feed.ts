import type { NameSheet } from './i18n'
import type { Chapter, Cue, FeedInfo, MatchEvent, Meta, Sample, StatsSnapshot, TalkItem } from './types'

// Columns in a streamed frame row: tick, then the stored match columns.
const C_TICK = 0
const C_PERIOD = 1
const C_CLOCK = 2
const C_BALL = 3
const C_OWNER = 6
const C_STATE = 7
const C_PLAYERS = 8

type Listener = () => void

export interface FeedSnapshot {
  connected: boolean
  meta: Meta | null
  speed: number
  playing: boolean
  score: [number, number]
  lineup: string[]
  events: MatchEvent[]
  tick: number
  clock: number
  period: number
  stats: StatsSnapshot | null
  cues: Cue[]
  talkback: TalkItem[]
  asking: { feed: string; question: string } | null
  answer: { feed: string; question: string; answer: string; at: number } | null
  feeds: FeedInfo[]
  names: NameSheet
  chapters: Chapter[]
  /** lets this viewer ask for a speech token, for questions by voice */
  ticket: string | null
}

/**
 * The live match feed. Frames and events arrive from the server's match clock;
 * the feed plays them back smoothly and releases each event the moment the
 * picture reaches it.
 */
export class MatchFeed {
  private ws: WebSocket | null = null
  private frames = new Map<number, number[]>()
  private latest = -1
  private pending: MatchEvent[] = []
  private listeners = new Set<Listener>()
  private snap: FeedSnapshot = {
    connected: false, meta: null, speed: 1, playing: true,
    score: [0, 0], lineup: [], events: [], tick: 0, clock: 0, period: 1, stats: null,
    cues: [], talkback: [], asking: null, answer: null, feeds: [], names: {}, chapters: [], ticket: null,
  }
  private pendingCues: Cue[] = []
  /** stretches of the match kept in memory for replays, however old */
  private pinned: [number, number][] = []
  private cueListeners = new Set<(c: Cue) => void>()
  private feeds: string[]
  private pendingStats: StatsSnapshot[] = []
  /** jumps asked of this connection and not yet answered: until they are, what arrives is from the old position */
  private seeking = 0
  private greeted = false
  renderTick = 0
  private matchId: string
  private started = false

  private tickForMinute(meta: Meta, minute: number) {
    const clock = minute * 60
    const period = clock < 45 * 60 ? meta.periods[0] : meta.periods[1]
    return period.start_tick + (clock - period.start_clock) * meta.hz
  }

  /** where to pick up when this feed replaces another (a viewer added their own broadcast) */
  private resumeAt: number | null

  constructor(matchId: string, feeds: string[] = [], resumeAt: number | null = null) {
    this.matchId = matchId
    this.feeds = feeds
    this.resumeAt = resumeAt
  }

  /** Called with each cue the moment the picture reaches it. */
  onCue(fn: (c: Cue) => void) {
    this.cueListeners.add(fn)
    return () => {
      this.cueListeners.delete(fn)
    }
  }

  /** Cues already received but not yet on air (for preloading audio). */
  get upcoming() {
    return this.pendingCues
  }

  connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const q = new URLSearchParams()
    if (this.feeds.length) q.set('feeds', this.feeds.join(','))
    // a reconnect, or a feed added mid-match, opens where the viewer is rather than at kick-off
    const from = this.started ? Math.round(this.renderTick) : this.resumeAt
    if (from) q.set('from', String(from))
    const ws = new WebSocket(`${proto}://${location.host}/ws/matches/${this.matchId}${q.toString() ? `?${q}` : ''}`)
    this.ws = ws
    this.seeking = 0
    this.greeted = false
    ws.onopen = () => this.update({ connected: true })
    ws.onclose = () => {
      if (this.film) ((window as unknown as { __gantryCues?: unknown[] }).__gantryCues ??= []).push({ t: performance.now(), id: 'CLOSED', at: this.renderTick })
      if (this.ws !== ws) return
      this.update({ connected: false })
      setTimeout(() => this.ws === ws && this.connect(), 1500)
    }
    ws.onmessage = (msg) => this.onMessage(JSON.parse(msg.data))
  }

  close() {
    const ws = this.ws
    this.ws = null
    ws?.close()
  }

  subscribe(fn: Listener) {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  get snapshot() {
    return this.snap
  }

  private update(patch: Partial<FeedSnapshot>) {
    this.snap = { ...this.snap, ...patch }
    this.listeners.forEach((fn) => fn())
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private onMessage(msg: any) {
    if (msg.type === 'hello') {
      this.update({ meta: msg.meta, feeds: msg.feeds ?? [], names: msg.names ?? {}, chapters: msg.chapters ?? [], ticket: msg.ticket ?? null })
      if (this.started) {
        // a reconnect: the stream already opens where the viewer was; carry on at the same speed
        this.send({ type: 'control', speed: this.snap.speed, playing: this.snap.playing })
        return
      }
      // ?t=<tick> or ?minute=<n> opens the match at a given moment
      const q = new URLSearchParams(location.search)
      const start = this.resumeAt !== null ? null : q.has('t') ? Number(q.get('t')) : q.has('minute') ? this.tickForMinute(msg.meta, Number(q.get('minute'))) : null
      if (start !== null && Number.isFinite(start)) this.seek(start)
      this.started = true
      if (q.has('speed')) this.setSpeed(Number(q.get('speed')))
    } else if (msg.type === 'state') {
      // the first state comes with the connection; each one after it answers a jump, in order
      if (!this.greeted) this.greeted = true
      else this.seeking = Math.max(0, this.seeking - 1)
      if (this.seeking) return
      this.frames.clear()
      this.latest = msg.tick - 1
      this.renderTick = msg.tick
      this.pending = []
      this.pendingStats = []
      this.pendingCues = []
      this.update({ score: msg.score, lineup: msg.lineup, events: msg.events, tick: msg.tick, stats: msg.stats ?? null, cues: [] })
    } else if (this.seeking && (msg.type === 'frames' || msg.type === 'cues' || msg.type === 'talkback')) {
      return
    } else if (msg.type === 'frames') {
      for (const row of msg.frames as number[][]) {
        this.frames.set(row[C_TICK], row)
        this.latest = Math.max(this.latest, row[C_TICK])
      }
      this.pending.push(...(msg.events as MatchEvent[]))
      if (msg.stats) this.pendingStats.push(...(msg.stats as StatsSnapshot[]))
    } else if (msg.type === 'clip') {
      for (const row of msg.frames as number[][]) this.frames.set(row[C_TICK], row)
    } else if (msg.type === 'cues') {
      if (this.film) {
        const w = window as unknown as { __gantryCues?: unknown[] }
        for (const c of msg.cues as Cue[]) (w.__gantryCues ??= []).push({ t: performance.now(), id: c.id, tick: c.tick, kind: c.kind, at: this.renderTick })
      }
      this.pendingCues.push(...(msg.cues as Cue[]))
      this.pendingCues.sort((a, b) => a.tick - b.tick)
    } else if (msg.type === 'answer') {
      this.update({ asking: null, answer: { feed: msg.feed, question: msg.question, answer: msg.answer, at: performance.now() } })
    } else if (msg.type === 'talkback') {
      this.update({ talkback: [...this.snap.talkback, ...(msg.items as TalkItem[])].slice(-80) })
      // keep about a minute and a half behind the picture, plus anything pinned for a replay
      const floor = Math.floor(this.renderTick) - 900
      for (const k of this.frames.keys()) {
        if (k < floor && !this.pinned.some(([a, b]) => k >= a && k < b)) this.frames.delete(k)
      }
    }
  }

  send(msg: object) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg))
  }

  setSpeed(speed: number) {
    this.send({ type: 'control', speed })
    this.update({ speed })
  }

  setPlaying(playing: boolean) {
    this.send({ type: 'control', playing })
    this.update({ playing })
  }

  /** Put a cue on air right now (used by the highlights package, which runs on its own clock). */
  inject(c: Cue) {
    this.update({ cues: [...this.snap.cues, c].slice(-60) })
    this.cueListeners.forEach((fn) => fn(c))
  }

  /** Put on air now any cues waiting that match, without waiting for the picture (used while the picture holds at a whistle). */
  releaseEarly(match: (c: Cue) => boolean) {
    const now = this.pendingCues.filter(match)
    if (!now.length) return
    this.pendingCues = this.pendingCues.filter((c) => !match(c))
    this.update({ cues: [...this.snap.cues, ...now].slice(-60) })
    for (const c of now) this.cueListeners.forEach((fn) => fn(c))
  }

  /** Ask the crew a question on one feed. The answer arrives as cues, like everything else. */
  ask(feedId: string, question: string) {
    this.send({ type: 'ask', feed: feedId, question })
    this.update({ asking: { feed: feedId, question }, answer: null })
    // if no answer comes back, let the viewer ask again
    window.setTimeout(() => {
      if (this.snap.asking?.question === question) this.update({ asking: null })
    }, 25000)
  }

  /** Ask the server for a stretch of the match the viewer has already passed. */
  requestClip(from: number, to: number) {
    this.pinned.push([from, to])
    this.send({ type: 'clip', from, to })
  }

  /** Let replay frames go once the replay or highlights are over. */
  unpinAll() {
    this.pinned = []
  }

  hasFrames(from: number, to: number) {
    return this.frames.has(from) && this.frames.has(to - 1) && this.frames.has(Math.floor((from + to) / 2))
  }

  seek(tick: number) {
    if (this.ws?.readyState !== WebSocket.OPEN) return
    this.seeking += 1
    this.send({ type: 'seek', tick: Math.round(tick) })
  }

  /** Move the playhead forward by `dtMs` of wall time. */
  /** filming: the picture moves exactly with the recording's clock, and tells the server how far it has got */
  readonly film = new URLSearchParams(location.search).has('film')
  private filmSent = -1

  advance(dtMs: number) {
    if (this.latest < 0) return
    const { speed, playing } = this.snap
    if (this.film) {
      if (playing) this.renderTick = Math.min(this.renderTick + (dtMs / 100) * speed, this.latest)
      ;(window as unknown as { __gantryFilmTick?: number }).__gantryFilmTick = this.renderTick
      if (Math.abs(this.renderTick - this.filmSent) >= 5) {
        this.filmSent = this.renderTick
        this.send({ type: 'film', tick: Math.round(this.renderTick) })
      }
      this.release()
      return
    }
    if (playing) this.renderTick += (dtMs / 100) * speed
    // stay a little behind the newest frame so there is always one to blend towards
    const target = this.latest - 1.5 * Math.max(1, speed)
    if (this.renderTick > this.latest) this.renderTick = this.latest
    else if (this.renderTick < target - 12 * Math.max(1, speed)) this.renderTick = target
    else if (playing) this.renderTick += (target - this.renderTick) * Math.min(1, dtMs / 1000)
    this.release()
  }

  private release() {
    // the newest stats the picture has reached
    let stats: StatsSnapshot | null = null
    while (this.pendingStats.length && this.pendingStats[0].tick <= this.renderTick) stats = this.pendingStats.shift()!
    if (stats) this.update({ stats })
    if (this.pendingCues.length && this.pendingCues[0].tick <= this.renderTick) {
      const due: Cue[] = []
      while (this.pendingCues.length && this.pendingCues[0].tick <= this.renderTick) due.push(this.pendingCues.shift()!)
      // a cue that fell far behind the picture is no longer worth airing; a highlights package always is
      const late = (c: Cue) => (c.kind === 'reel' ? Infinity : c.kind === 'replay' ? 80 : 30)
      const fresh = due.filter((c) => this.renderTick - c.tick < late(c))
      this.update({ cues: [...this.snap.cues, ...fresh].slice(-60) })
      for (const c of fresh) this.cueListeners.forEach((fn) => fn(c))
    }
    const due = this.pending.filter((e) => e.tick <= this.renderTick)
    const row = this.frames.get(Math.floor(this.renderTick))
    if (!due.length) {
      if (row && Math.floor(row[C_CLOCK]) !== Math.floor(this.snap.clock)) {
        this.update({ clock: row[C_CLOCK], period: row[C_PERIOD], tick: row[C_TICK] })
      }
      return
    }
    this.pending = this.pending.filter((e) => e.tick > this.renderTick)
    let { score, lineup } = this.snap
    for (const e of due) {
      if (e.type === 'goal') score = e.score as [number, number]
      if (e.type === 'substitution') {
        lineup = [...lineup]
        lineup[e.slot_index as number] = e.on as string
      }
    }
    this.update({
      score, lineup,
      events: [...this.snap.events, ...due].slice(-200),
      clock: row ? row[C_CLOCK] : this.snap.clock,
      period: row ? row[C_PERIOD] : this.snap.period,
      tick: row ? row[C_TICK] : this.snap.tick,
    })
  }

  /** The match at the playhead, blended between the two nearest frames. */
  sample(): Sample | null {
    return this.sampleAt(this.renderTick)
  }

  /** The match at any tick still in memory. */
  sampleAt(t: number): Sample | null {
    const i = Math.floor(t)
    const a = this.frames.get(i)
    if (!a) return null
    const b = this.frames.get(i + 1) ?? a
    const f = t - i
    const players = new Float32Array(44)
    for (let k = 0; k < 44; k++) {
      const va = a[C_PLAYERS + k]
      const vb = b[C_PLAYERS + k]
      // a jump of more than a few metres is a substitution or a new half: don't blend it
      players[k] = Math.abs(vb - va) > 4 ? vb : va + (vb - va) * f
    }
    const ball: [number, number, number] = [0, 0, 0]
    const jump = Math.hypot(b[C_BALL] - a[C_BALL], b[C_BALL + 1] - a[C_BALL + 1]) > 8
    for (let k = 0; k < 3; k++) {
      const va = a[C_BALL + k]
      const vb = b[C_BALL + k]
      ball[k] = jump ? vb : va + (vb - va) * f
    }
    return {
      tick: t, period: a[C_PERIOD], clock: a[C_CLOCK] + (b[C_CLOCK] - a[C_CLOCK]) * f,
      ball, owner: a[C_OWNER], state: a[C_STATE], players,
    }
  }
}
