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

export const FEEDS = [
  { id: 'casual_en', label: 'New fan', lang: 'en' },
  { id: 'analyst_en', label: 'Analyst', lang: 'en' },
  { id: 'home_zh', label: '中文 · No.10', lang: 'zh' },
  { id: 'audio_en', label: 'Audio described', lang: 'en' },
] as const

export type FeedId = (typeof FEEDS)[number]['id']
