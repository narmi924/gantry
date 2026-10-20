import * as THREE from 'three'
import type { MatchEvent, Sample } from '../types'
import { toWorld } from './world'

/**
 * Drawings for a replay, seen on every feed: the run of the player the replay is
 * about, and each pass of the move as it is played.
 */
export class ReplayLayer {
  readonly group = new THREE.Group()
  private trail: THREE.Mesh | null = null
  private trailMat = new THREE.MeshBasicMaterial({ color: '#ffffff', transparent: true, opacity: 0.9, depthWrite: false })
  private passes = new Map<number, THREE.Mesh>()
  private passMat = new THREE.MeshBasicMaterial({ color: '#ffffff', transparent: true, opacity: 0.85, depthWrite: false })
  private lastBuilt = -1

  constructor() {
    this.group.visible = false
  }

  start(teamColor: string) {
    this.clear()
    this.trailMat.color.set(teamColor).lerp(new THREE.Color('#ffffff'), 0.25)
    this.group.visible = true
  }

  stop() {
    this.clear()
    this.group.visible = false
  }

  private clear() {
    if (this.trail) {
      this.group.remove(this.trail)
      this.trail.geometry.dispose()
      this.trail = null
    }
    for (const m of this.passes.values()) {
      this.group.remove(m)
      m.geometry.dispose()
    }
    this.passes.clear()
    this.lastBuilt = -1
  }

  /**
   * `path` returns the focus player's position at a tick; `events` are the match events up to now.
   */
  update(from: number, tick: number, focus: number, path: (t: number) => Sample | null, events: MatchEvent[], team: number | null) {
    if (!this.group.visible) return
    // the run, rebuilt a few times a second as it grows
    if (focus >= 0 && Math.floor(tick) - this.lastBuilt >= 2) {
      this.lastBuilt = Math.floor(tick)
      const pts: THREE.Vector3[] = []
      for (let t = from; t <= tick; t += 3) {
        const s = path(t)
        if (s) pts.push(toWorld(s.players[focus * 2], s.players[focus * 2 + 1], 0.06))
      }
      if (this.trail) {
        this.group.remove(this.trail)
        this.trail.geometry.dispose()
        this.trail = null
      }
      if (pts.length >= 2) {
        const curve = new THREE.CatmullRomCurve3(pts)
        this.trail = new THREE.Mesh(new THREE.TubeGeometry(curve, Math.max(8, pts.length * 3), 0.12, 6, false), this.trailMat)
        this.trail.renderOrder = 4
        this.group.add(this.trail)
      }
    }
    // each pass of the move, drawn once it has arrived
    for (const e of events) {
      if (e.type !== 'pass' || e.outcome !== 'complete' || e.team !== team) continue
      if ((e.start_tick as number) < from || e.tick > tick || this.passes.has(e.id)) continue
      const a = toWorld(e.x as number, e.y as number, 0.07)
      const b = toWorld(e.end_x as number, e.end_y as number, 0.07)
      const mid = a.clone().add(b).multiplyScalar(0.5)
      mid.y = (e.lofted ? 0.18 : 0.04) * (e.length as number) + 0.25
      const m = new THREE.Mesh(new THREE.TubeGeometry(new THREE.QuadraticBezierCurve3(a, mid, b), 28, 0.07, 6, false), this.passMat)
      m.renderOrder = 4
      this.passes.set(e.id, m)
      this.group.add(m)
    }
  }
}
