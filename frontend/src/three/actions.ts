import type { Sample } from '../types'

/** What a player's body is doing beyond running: striking the ball, or a goalkeeper diving. */
export interface Action {
  kind: 'kick' | 'dive'
  /** match tick of the contact */
  at: number
  /** for a dive: -1 or 1, the keeper's left or right */
  side: number
}

/**
 * Read kicks and dives straight from the tracking data around the playhead: a kick is the moment the
 * player who has the ball lets it go; a dive is a fast ball flying past a goalkeeper. The feed keeps
 * a second or so of frames ahead of the picture, so the backswing starts before the contact.
 */
export function readActions(t: number, sampleAt: (tick: number) => Sample | null, keepers: [number, number]): Map<number, Action> {
  const out = new Map<number, Action>()
  const base = Math.floor(t)
  let prev: Sample | null = sampleAt(base - 7)
  for (let k = base - 6; k <= base + 7; k++) {
    const cur = sampleAt(k)
    if (!cur || !prev) {
      prev = cur
      continue
    }
    // the player on the ball lets it go: a pass, a cross, a shot or a clearance
    if (prev.owner >= 0 && cur.owner < 0 && !out.has(prev.owner)) {
      out.set(prev.owner, { kind: 'kick', at: k - 1, side: 1 })
    }
    // a ball travelling faster than 12 m/s that passes within reach of a goalkeeper between two frames
    const dx = cur.ball[0] - prev.ball[0]
    const dy = cur.ball[1] - prev.ball[1]
    const speed = Math.hypot(dx, dy) * 10
    if (speed > 12) {
      for (const gk of keepers) {
        if (out.has(gk)) continue
        const gx = cur.players[gk * 2]
        const gy = cur.players[gk * 2 + 1]
        const len2 = dx * dx + dy * dy
        const f = Math.max(0, Math.min(1, ((gx - prev.ball[0]) * dx + (gy - prev.ball[1]) * dy) / len2))
        const px = prev.ball[0] + dx * f
        const py = prev.ball[1] + dy * f
        const d = Math.hypot(px - gx, py - gy)
        if (d < 3.5 && d > 0.3) out.set(gk, { kind: 'dive', at: k, side: py > gy ? 1 : -1 })
      }
    }
    prev = cur
  }
  return out
}
