export interface Player {
  id: string
  team: number
  number: number
  first: string
  last: string
  name: string
  position: string
}

export interface TeamColors {
  shirt: string
  shorts: string
  socks: string
  text: string
  gk_shirt: string
  gk_shorts: string
}

export interface Team {
  index: number
  name: string
  short: string
  code: string
  formation: string
  colors: TeamColors
  players: Player[]
  starters: string[]
  slots: string[]
}

export interface Period {
  period: number
  start_tick: number
  end_tick: number
  start_clock: number
}

export interface Meta {
  id: string
  hz: number
  pitch: { length: number; width: number }
  frames: number
  periods: Period[]
  teams: [Team, Team]
}

export interface MatchEvent {
  id: number
  tick: number
  period: number
  clock: number
  type: string
  team?: number
  player?: string
  [key: string]: unknown
}

/** One moment of the match, already interpolated for drawing. */
export interface Sample {
  tick: number
  period: number
  clock: number
  ball: [number, number, number]
  owner: number
  state: number
  players: Float32Array // x0, y0, x1, y1, ...
}

export const STATE_PLAY = 0

export interface TeamStats {
  possession: number
  passes: number
  completion: number | null
  difficulty: number | null
  shots: number
  on_target: number
  xg: number
  ppda: number | null
  distance_km: number
  sprints: number
  corners: number
  fouls: number
  field_tilt: number | null
}

export interface StatsSnapshot {
  tick: number
  teams: [TeamStats, TeamStats]
  momentum: { minute: number; value: number }[]
  control: { turnovers_per_min: number; completion: number; chaos: number; tempo_passes_per_min: number }
}

export interface Cue {
  id: string
  feed: string
  tick: number
  kind: 'line' | 'graphic' | 'replay' | 'reel'
  moment: string
  text?: string | null
  audio?: string | null
  seconds?: number | null
  excited?: boolean
  interrupt?: boolean
  graphic?: { type: string; seconds: number; player?: string; profile?: Record<string, unknown> } | null
  replay?: ReplayCall | null
  reel?: Reel | null
  source: string
}

export interface ReelLine {
  text: string
  audio: string | null
  seconds: number
}

export interface ReelClip {
  from: number
  to: number
  team: number
  focus: string | null
  why: string
  angles: Record<string, ReplayAngle>
  lines: Record<string, ReelLine>
}

export interface FeedReport {
  headline: string
  summary: string
  star: string | null
}

export interface Reel {
  clips: ReelClip[]
  reports: Record<string, FeedReport>
  when: 'half_time' | 'full_time'
}

export type ReplayAngle = 'behind_goal' | 'high' | 'follow' | 'reverse'

export interface ReplayCall {
  from: number
  to: number
  angle: ReplayAngle
  focus: string | null
  speed: number
  team: number | null
}

export interface TalkItem {
  tick: number
  who: string
  to: string | null
  text: string
  feed: string | null
  source: string
  moment?: string | null
}

/** A feed is one audience in one language, e.g. "home_en" or "analyst_es". */
export type FeedId = string
export type Audience = 'casual' | 'analyst' | 'home' | 'audio'

export interface FeedInfo {
  id: FeedId
  name: string
  audience: Audience
  label: string
  language: string
  language_name: string
  locale: string
  rtl: boolean
  follow?: string | null
  club?: number | null
  metric?: string | null
  custom?: boolean
}

export const DEFAULT_FEEDS: FeedId[] = ['casual_en', 'analyst_en', 'home_en', 'audio_en']

export const AUDIENCE_LABEL: Record<Audience, string> = {
  casual: 'New fan',
  analyst: 'Analyst',
  home: 'Following No. 10',
  audio: 'Audio described',
}

export const audienceOf = (id: FeedId) => (id.split('_')[0] || 'casual') as Audience
export const languageOf = (id: FeedId) => (id.split('_')[1] || 'en').split('.')[0]

/** A feed id the server understands: an audience in a language, optionally with a club, a player and a number. */
export const FEED_ID = /^(casual|analyst|home|audio)_(en|es|pt|fr|ar|hi|id|zh)(\.(KSM|ASH|-)\.((KSM|ASH)-\d+|-)\.(speed|distance|passing|shots|-))?$/

export interface Chapter {
  label: string
  tick: number
  kind: 'kickoff' | 'goal' | 'half_time' | 'full_time'
  team?: number
}

/** The player each audience's camera follows, if any. */
export const FOLLOWS: Partial<Record<Audience, string>> = { home: 'KSM-10' }
