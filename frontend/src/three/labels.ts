import type { MatchEvent, Player, Sample, Team } from '../types'
import { STATE_PLAY } from '../types'
import type { View } from './broadcast3d'

interface Part {
  text: string
  bg: string
  fg: string
}

const PAPER = 'rgba(255,255,255,0.95)'
const INK = '#0b2236'

/** Tags drawn over one view: who has the ball, who is flying, how hard it was hit. */
export class Labels {
  private carrier = -1
  private since = 0

  draw(
    ctx: CanvasRenderingContext2D,
    view: View,
    s: Sample | null,
    lineup: (Player | undefined)[],
    teams: [Team, Team],
    events: MatchEvent[],
    now: number,
    dpr: number,
    pass: MatchEvent | null,
  ) {
    if (!s) return
    const r = view.spec.rect
    ctx.save()
    ctx.beginPath()
    ctx.rect(r.x * dpr, r.y * dpr, r.w * dpr, r.h * dpr)
    ctx.clip()
    const size = Math.round(Math.max(11, Math.min(16, r.h * 0.022)) * dpr)
    const px = (p: { x: number; y: number } | null) => (p ? { x: p.x * dpr, y: p.y * dpr } : null)
    const slotOf = (id?: unknown) => lineup.findIndex((p) => p?.id === id)
    const at = (k: number, z = 2.15) => px(view.project(s.players[k * 2], s.players[k * 2 + 1], z))

    // a sprint fast enough to be worth a speed tag, while it lasts
    let sprinter = -1
    for (let i = events.length - 1; i >= 0 && i > events.length - 40; i--) {
      const e = events[i]
      if (e.type !== 'sprint') continue
      if (s.tick > (e.end_tick as number) + 15) break
      const k = slotOf(e.player)
      const p = k >= 0 ? at(k) : null
      if (p && lineup[k]) {
        sprinter = k
        this.tag(ctx, p, teams[k < 11 ? 0 : 1].colors.shirt, [
          { text: `${lineup[k]!.number}  ${lineup[k]!.last}`, bg: PAPER, fg: INK },
          { text: `${(e.speed_kmh as number).toFixed(1)} km/h`, bg: INK, fg: '#ffffff' },
        ], size, dpr)
      }
      break
    }

    // shot speed, for a few seconds after the strike
    for (let i = events.length - 1; i >= 0 && i > events.length - 12; i--) {
      const e = events[i]
      if (e.type !== 'shot') continue
      if (s.tick - e.tick > 35) break
      const p = px(view.project(e.x as number, e.y as number, 0.6))
      if (p) {
        const parts = [
          { text: 'Shot', bg: PAPER, fg: INK },
          { text: `${e.speed_kmh} km/h`, bg: INK, fg: '#ffffff' },
        ]
        if (view.spec.analyst) parts.push({ text: `xG ${(e.xg as number).toFixed(2)}`, bg: '#1d3a5c', fg: '#ffffff' })
        this.tag(ctx, p, teams[e.team ?? 0].colors.shirt, parts, size, dpr)
      }
      break
    }

    // the analyst sees how hard the last pass was
    if (view.spec.analyst && pass) {
      const mx = ((pass.x as number) + (pass.end_x as number)) / 2
      const my = ((pass.y as number) + (pass.end_y as number)) / 2
      const p = px(view.project(mx, my, 1.4))
      if (p) {
        this.tag(ctx, p, '#ffb02e', [
          { text: `Pass ${Math.round(pass.length as number)} m`, bg: PAPER, fg: INK },
          { text: `difficulty ${pass.difficulty}`, bg: INK, fg: '#ffffff' },
        ], size, dpr)
      }
    }

    // the player on the ball, once he has had it for a moment
    if (s.owner !== this.carrier) {
      this.carrier = s.owner
      this.since = now
    }
    if (s.state === STATE_PLAY && s.owner >= 0 && s.owner !== sprinter && now - this.since > 350) {
      const k = s.owner
      const player = lineup[k]
      const p = at(k)
      if (player && p) {
        this.tag(ctx, p, teams[k < 11 ? 0 : 1].colors.shirt, [{ text: `${player.number}  ${player.last}`, bg: PAPER, fg: INK }], size, dpr)
      }
    }
    ctx.restore()
  }

  private tag(ctx: CanvasRenderingContext2D, p: { x: number; y: number }, accent: string, parts: Part[], size: number, dpr: number) {
    ctx.font = `650 ${size}px Archivo`
    ctx.fontStretch = 'semi-condensed'
    ctx.textBaseline = 'middle'
    ctx.textAlign = 'left'
    const padX = size * 0.55
    const widths = parts.map((part) => ctx.measureText(part.text).width + padX * 2)
    const bar = 4 * dpr
    const bw = bar + widths.reduce((a, b) => a + b, 0)
    const bh = size * 1.6
    let x = p.x - bw / 2
    const y = p.y - bh - 6 * dpr
    ctx.save()
    ctx.beginPath()
    ctx.roundRect(x, y, bw, bh, 3 * dpr)
    ctx.clip()
    ctx.fillStyle = accent
    ctx.fillRect(x, y, bar, bh)
    x += bar
    parts.forEach((part, i) => {
      ctx.fillStyle = part.bg
      ctx.fillRect(x, y, widths[i], bh)
      ctx.fillStyle = part.fg
      ctx.fillText(part.text, x + padX, y + bh / 2 + dpr)
      x += widths[i]
    })
    ctx.restore()
    ctx.fillStyle = parts[0].bg
    ctx.beginPath()
    ctx.moveTo(p.x - 5 * dpr, y + bh)
    ctx.lineTo(p.x + 5 * dpr, y + bh)
    ctx.lineTo(p.x, y + bh + 5 * dpr)
    ctx.fill()
    ctx.fontStretch = 'normal'
  }
}
